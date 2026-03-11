#!/usr/bin/env node

/**
 * build-registry.js
 *
 * Walks skills/, agents/, and collections/ directories, validates each
 * manifest against its schema, and assembles registry.json — the master
 * index that powers the CLI, landing site, and curl installer.
 *
 * Usage:
 *   node scripts/build-registry.js                  # build registry.json at repo root
 *   node scripts/build-registry.js --out dist/      # write to a custom directory
 *   node scripts/build-registry.js --validate-only  # validate without writing
 */

const fs = require("fs");
const path = require("path");

// ─── Config ─────────────────────────────────────────────────────

const ROOT = path.resolve(__dirname, "..");
const SKILLS_DIR = path.join(ROOT, "skills");
const AGENTS_DIR = path.join(ROOT, "agents");
const COLLECTIONS_DIR = path.join(ROOT, "collections");
const SCHEMAS_DIR = path.join(ROOT, "schemas");
const TARGETS_DIR = path.join(ROOT, "targets");

const REPO_BASE_URL =
  process.env.REPO_BASE_URL ||
  "https://raw.githubusercontent.com/eugeneacn/dropkit/main";

const SITE_BASE_URL =
  process.env.SITE_BASE_URL || "https://github.com/eugeneacn/dropkit";

// ─── CLI args ───────────────────────────────────────────────────

const args = process.argv.slice(2);
let outDir = ROOT;
let validateOnly = false;
let verbose = false;

for (let i = 0; i < args.length; i++) {
  if (args[i] === "--out") outDir = path.resolve(args[++i]);
  if (args[i] === "--validate-only") validateOnly = true;
  if (args[i] === "--verbose" || args[i] === "-v") verbose = true;
}

// ─── Lightweight JSON Schema validator ──────────────────────────
// Validates required fields, types, and enum values without a
// full JSON Schema library. Keeps the build script zero-dep.

function validateManifest(manifest, type) {
  const errors = [];
  const schemaPath = path.join(SCHEMAS_DIR, `${type}.schema.json`);

  // If a formal schema file exists, validate required fields from it
  if (fs.existsSync(schemaPath)) {
    const schema = JSON.parse(fs.readFileSync(schemaPath, "utf-8"));
    const required = schema.required || [];
    for (const field of required) {
      if (manifest[field] === undefined || manifest[field] === null) {
        errors.push(`Missing required field: "${field}"`);
      }
    }

    // Validate property types
    if (schema.properties) {
      for (const [key, def] of Object.entries(schema.properties)) {
        if (manifest[key] === undefined) continue;
        const val = manifest[key];
        const expectedType = def.type;

        if (expectedType === "string" && typeof val !== "string") {
          errors.push(`"${key}" must be a string, got ${typeof val}`);
        }
        if (expectedType === "array" && !Array.isArray(val)) {
          errors.push(`"${key}" must be an array, got ${typeof val}`);
        }
        if (
          expectedType === "object" &&
          (typeof val !== "object" || Array.isArray(val))
        ) {
          errors.push(`"${key}" must be an object, got ${typeof val}`);
        }

        // Validate enum values
        if (def.enum && !def.enum.includes(val)) {
          errors.push(
            `"${key}" must be one of [${def.enum.join(", ")}], got "${val}"`,
          );
        }
      }
    }
  }

  // Hard-coded baseline checks regardless of schema file
  if (type === "skill" || type === "agent") {
    if (!manifest.id) errors.push('Missing "id"');
    if (!manifest.name) errors.push('Missing "name"');
    if (!manifest.version) errors.push('Missing "version"');
    if (!manifest.description) errors.push('Missing "description"');

    if (manifest.id && !/^[a-z0-9][a-z0-9-]*[a-z0-9]$/.test(manifest.id)) {
      errors.push(
        `"id" must be lowercase alphanumeric with hyphens: "${manifest.id}"`,
      );
    }

    if (manifest.version && !/^\d+\.\d+\.\d+/.test(manifest.version)) {
      errors.push(`"version" must be semver: "${manifest.version}"`);
    }
  }

  if (type === "skill") {
    if (!manifest.category) errors.push('Missing "category"');
    if (!manifest.targets) errors.push('Missing "targets"');
    if (
      manifest.targets &&
      !manifest.targets.default &&
      !Object.keys(manifest.targets).some((k) => k !== "default")
    ) {
      errors.push('"targets" must have at least one entry');
    }
  }

  return errors;
}

// ─── Directory walkers ──────────────────────────────────────────

function findManifests(baseDir, manifestName = "manifest.json") {
  const results = [];
  if (!fs.existsSync(baseDir)) return results;

  function walk(dir) {
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(fullPath);
      } else if (entry.name === manifestName) {
        results.push(fullPath);
      }
    }
  }

  walk(baseDir);
  return results;
}

function loadTargets() {
  const targets = {};
  if (!fs.existsSync(TARGETS_DIR)) return targets;

  for (const file of fs.readdirSync(TARGETS_DIR)) {
    if (!file.endsWith(".json")) continue;
    const data = JSON.parse(
      fs.readFileSync(path.join(TARGETS_DIR, file), "utf-8"),
    );
    targets[data.id] = data;
  }
  return targets;
}

// ─── Skill & agent file validation ──────────────────────────────

function validateReferencedFiles(manifest, manifestDir, type) {
  const warnings = [];
  const fileField = type === "skill" ? "skill.md" : "agent.md";

  // Check that the canonical prompt file exists
  const canonicalFile = path.join(manifestDir, fileField);
  if (!fs.existsSync(canonicalFile)) {
    // Check if a default target points somewhere else
    const defaultTarget = manifest.targets?.default?.file;
    if (defaultTarget) {
      const defaultPath = path.join(manifestDir, defaultTarget);
      if (!fs.existsSync(defaultPath)) {
        warnings.push(`Default file missing: ${defaultTarget}`);
      }
    } else {
      warnings.push(`Canonical file missing: ${fileField}`);
    }
  }

  // Check override files
  if (manifest.targets) {
    for (const [targetId, targetConf] of Object.entries(manifest.targets)) {
      if (targetId === "default") continue;
      if (typeof targetConf === "object" && targetConf.file) {
        const overridePath = path.join(manifestDir, targetConf.file);
        if (!fs.existsSync(overridePath)) {
          warnings.push(
            `Override file missing for "${targetId}": ${targetConf.file}`,
          );
        }
      }
    }
  }

  // Check template files
  if (manifest.templates) {
    const templatesDir = path.join(manifestDir, "templates");
    if (!fs.existsSync(templatesDir)) {
      warnings.push("Templates referenced but templates/ directory missing");
    }
  }

  return warnings;
}

// ─── Build install URLs ─────────────────────────────────────────

function buildInstallUrls(manifest, relativePath, targets) {
  const install = {};

  for (const targetId of Object.keys(targets)) {
    // Only generate URL if skill supports this target (or has a default)
    if (manifest.targets?.[targetId] || manifest.targets?.default) {
      install[targetId] =
        `curl -sL ${SITE_BASE_URL}/i/${targetId}/${manifest.id} | bash`;
    }
  }

  // Always include a generic npx command
  install.npx = `npx dropkit add ${manifest.id}`;

  return install;
}

// ─── Main ───────────────────────────────────────────────────────

function main() {
  const targets = loadTargets();
  const errors = [];
  const warnings = [];
  const stats = {
    skills: 0,
    agents: 0,
    collections: 0,
    errors: 0,
    warnings: 0,
  };

  console.log("🔍 Scanning repository...\n");

  // ── Process skills ──

  const skills = [];
  const skillManifests = findManifests(SKILLS_DIR);

  for (const manifestPath of skillManifests) {
    const manifestDir = path.dirname(manifestPath);
    const relativePath = path.relative(ROOT, manifestDir);
    const raw = fs.readFileSync(manifestPath, "utf-8");

    let manifest;
    try {
      manifest = JSON.parse(raw);
    } catch (e) {
      errors.push({
        path: relativePath,
        message: `Invalid JSON: ${e.message}`,
      });
      stats.errors++;
      continue;
    }

    // Validate manifest
    const validationErrors = validateManifest(manifest, "skill");
    if (validationErrors.length > 0) {
      for (const err of validationErrors) {
        errors.push({ path: relativePath, message: err });
        stats.errors++;
      }
      continue;
    }

    // Validate referenced files exist
    const fileWarnings = validateReferencedFiles(
      manifest,
      manifestDir,
      "skill",
    );
    for (const w of fileWarnings) {
      warnings.push({ path: relativePath, message: w });
      stats.warnings++;
    }

    // Determine supported targets
    const supportedTargets = Object.keys(manifest.targets || {}).filter(
      (k) => k !== "default",
    );
    if (manifest.targets?.default) supportedTargets.push("generic");

    // Build registry entry
    skills.push({
      id: manifest.id,
      name: manifest.name,
      version: manifest.version,
      description: manifest.description,
      category: manifest.category,
      tags: manifest.tags || [],
      author: manifest.author || "dropkit",
      license: manifest.license || "MIT",
      deps: manifest.deps?.npm || [],
      input: manifest.input || {},
      output: manifest.output || {},
      targets: supportedTargets,
      path: relativePath,
      install: buildInstallUrls(manifest, relativePath, targets),
    });

    stats.skills++;
    if (verbose) console.log(`  ✔ skill: ${manifest.id} (${relativePath})`);
  }

  // ── Process agents ──

  const agents = [];
  const agentManifests = findManifests(AGENTS_DIR);

  for (const manifestPath of agentManifests) {
    const manifestDir = path.dirname(manifestPath);
    const relativePath = path.relative(ROOT, manifestDir);
    const raw = fs.readFileSync(manifestPath, "utf-8");

    let manifest;
    try {
      manifest = JSON.parse(raw);
    } catch (e) {
      errors.push({
        path: relativePath,
        message: `Invalid JSON: ${e.message}`,
      });
      stats.errors++;
      continue;
    }

    const validationErrors = validateManifest(manifest, "agent");
    if (validationErrors.length > 0) {
      for (const err of validationErrors) {
        errors.push({ path: relativePath, message: err });
        stats.errors++;
      }
      continue;
    }

    const fileWarnings = validateReferencedFiles(
      manifest,
      manifestDir,
      "agent",
    );
    for (const w of fileWarnings) {
      warnings.push({ path: relativePath, message: w });
      stats.warnings++;
    }

    const supportedTargets = Object.keys(manifest.targets || {}).filter(
      (k) => k !== "default",
    );
    if (manifest.targets?.default) supportedTargets.push("generic");

    agents.push({
      id: manifest.id,
      name: manifest.name,
      version: manifest.version,
      description: manifest.description,
      tags: manifest.tags || [],
      author: manifest.author || "dropkit",
      license: manifest.license || "MIT",
      skills: manifest.skills || [],
      targets: supportedTargets,
      path: relativePath,
      install: buildInstallUrls(manifest, relativePath, targets),
    });

    stats.agents++;
    if (verbose) console.log(`  ✔ agent: ${manifest.id} (${relativePath})`);
  }

  // ── Process collections ──

  const collections = [];
  if (fs.existsSync(COLLECTIONS_DIR)) {
    for (const file of fs.readdirSync(COLLECTIONS_DIR)) {
      if (!file.endsWith(".json")) continue;
      const filePath = path.join(COLLECTIONS_DIR, file);
      const raw = fs.readFileSync(filePath, "utf-8");

      let collection;
      try {
        collection = JSON.parse(raw);
      } catch (e) {
        errors.push({
          path: `collections/${file}`,
          message: `Invalid JSON: ${e.message}`,
        });
        stats.errors++;
        continue;
      }

      if (!collection.id || !collection.name) {
        errors.push({
          path: `collections/${file}`,
          message: 'Missing "id" or "name"',
        });
        stats.errors++;
        continue;
      }

      // Validate that all referenced skills/agents exist
      const skillIds = new Set(skills.map((s) => s.id));
      const agentIds = new Set(agents.map((a) => a.id));

      for (const sid of collection.skills || []) {
        if (!skillIds.has(sid)) {
          warnings.push({
            path: `collections/${file}`,
            message: `References unknown skill: "${sid}"`,
          });
          stats.warnings++;
        }
      }

      for (const aid of collection.agents || []) {
        if (!agentIds.has(aid)) {
          warnings.push({
            path: `collections/${file}`,
            message: `References unknown agent: "${aid}"`,
          });
          stats.warnings++;
        }
      }

      collections.push({
        id: collection.id,
        name: collection.name,
        description: collection.description || "",
        skills: collection.skills || [],
        agents: collection.agents || [],
        install: {
          npx: `npx dropkit add --collection ${collection.id}`,
          curl: `curl -sL ${SITE_BASE_URL}/i/collection/${collection.id} | bash`,
        },
      });

      stats.collections++;
      if (verbose) console.log(`  ✔ collection: ${collection.id}`);
    }
  }

  // ── Build category index ──

  const categories = {};
  for (const skill of skills) {
    if (!categories[skill.category]) {
      categories[skill.category] = { id: skill.category, count: 0, skills: [] };
    }
    categories[skill.category].count++;
    categories[skill.category].skills.push(skill.id);
  }

  // ── Assemble registry ──

  const registry = {
    version: "1.0.0",
    generated: new Date().toISOString(),
    stats: {
      skills: stats.skills,
      agents: stats.agents,
      collections: stats.collections,
      categories: Object.keys(categories).length,
    },
    categories: Object.values(categories),
    skills: skills.sort((a, b) => a.id.localeCompare(b.id)),
    agents: agents.sort((a, b) => a.id.localeCompare(b.id)),
    collections: collections.sort((a, b) => a.id.localeCompare(b.id)),
  };

  // ── Report ──

  console.log(`\n📊 Registry summary:`);
  console.log(`   Skills:      ${stats.skills}`);
  console.log(`   Agents:      ${stats.agents}`);
  console.log(`   Collections: ${stats.collections}`);
  console.log(
    `   Categories:  ${Object.keys(categories).length} (${Object.keys(categories).join(", ")})`,
  );

  if (warnings.length > 0) {
    console.log(`\n⚠  ${warnings.length} warning(s):`);
    for (const w of warnings) {
      console.log(`   ${w.path}: ${w.message}`);
    }
  }

  if (errors.length > 0) {
    console.log(`\n❌ ${errors.length} error(s):`);
    for (const e of errors) {
      console.log(`   ${e.path}: ${e.message}`);
    }
    console.log("\nRegistry build failed. Fix errors above and retry.");
    process.exit(1);
  }

  if (validateOnly) {
    console.log("\n✔ Validation passed.");
    process.exit(0);
  }

  // ── Write registry.json ──

  if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });
  const outFile = path.join(outDir, "registry.json");
  fs.writeFileSync(outFile, JSON.stringify(registry, null, 2) + "\n");
  console.log(
    `\n✔ Wrote ${outFile} (${(Buffer.byteLength(JSON.stringify(registry)) / 1024).toFixed(1)} KB)`,
  );
}

main();
