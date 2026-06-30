#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

function fail(msg) {
  console.error('ERROR: ' + msg);
  process.exit(1);
}

const inputPath = process.argv[2];
const outputPath = process.argv[3];
if (!inputPath || !outputPath) {
  fail('Usage: node ua-arch-analyze.js <input.json> <output.json>');
}

let raw;
try {
  raw = fs.readFileSync(inputPath, 'utf8');
} catch (e) {
  fail('Could not read input file: ' + e.message);
}

let data;
try {
  data = JSON.parse(raw);
} catch (e) {
  fail('Could not parse input JSON: ' + e.message);
}

const fileNodes = data.fileNodes || [];
const importEdges = data.importEdges || [];
const allEdges = data.allEdges || [];

const nodeById = new Map();
for (const n of fileNodes) nodeById.set(n.id, n);

// ---------- A. Directory Grouping ----------

function dirOf(filePath) {
  const parts = filePath.split('/');
  parts.pop();
  return parts;
}

const allPaths = fileNodes.map(n => n.filePath);
const splitPaths = allPaths.map(p => p.split('/'));

// compute common prefix (directory segments) shared by all files
function commonPrefix(paths) {
  if (paths.length === 0) return [];
  let prefix = paths[0].slice(0, -1); // exclude filename
  for (const p of paths.slice(1)) {
    const dirSegs = p.slice(0, -1);
    let i = 0;
    while (i < prefix.length && i < dirSegs.length && prefix[i] === dirSegs[i]) i++;
    prefix = prefix.slice(0, i);
    if (prefix.length === 0) break;
  }
  return prefix;
}

const prefixSegs = commonPrefix(splitPaths);

function topGroupFor(filePath) {
  const segs = filePath.split('/');
  const dirSegs = segs.slice(0, -1);
  const fileName = segs[segs.length - 1];
  if (dirSegs.length > prefixSegs.length) {
    return dirSegs[prefixSegs.length];
  }
  // file lives directly at the common-prefix level (no subdirectory)
  if (dirSegs.length === prefixSegs.length) {
    if (dirSegs.length > 0) {
      return dirSegs[dirSegs.length - 1]; // its immediate directory
    }
    // flat: root-level file, group by extension/pattern
    return classifyFlatFile(fileName);
  }
  return classifyFlatFile(fileName);
}

function classifyFlatFile(fileName) {
  if (/\.test\.|\.spec\.|^test_|_test\.go$|Test\.java$|_spec\.rb$|Test\.php$|Tests\.cs$/.test(fileName)) return 'test';
  if (/\.config\.|^config\./.test(fileName)) return 'config';
  if (fileName.endsWith('.md') || fileName.endsWith('.rst')) return 'documentation';
  if (fileName === 'Dockerfile' || fileName.startsWith('docker-compose')) return 'infrastructure';
  if (fileName.endsWith('.sql')) return 'data';
  return 'root';
}

const directoryGroups = {};
const groupForFile = new Map();
for (const n of fileNodes) {
  const g = topGroupFor(n.filePath);
  groupForFile.set(n.id, g);
  if (!directoryGroups[g]) directoryGroups[g] = [];
  directoryGroups[g].push(n.id);
}

// ---------- B. Node Type Grouping ----------

const nodeTypeGroups = {};
for (const n of fileNodes) {
  const t = n.type || 'file';
  if (!nodeTypeGroups[t]) nodeTypeGroups[t] = [];
  nodeTypeGroups[t].push(n.id);
}

// ---------- C. Import Adjacency Matrix ----------

const fanOut = {};
const fanIn = {};
for (const n of fileNodes) {
  fanOut[n.id] = 0;
  fanIn[n.id] = 0;
}
for (const e of importEdges) {
  if (fanOut[e.source] !== undefined) fanOut[e.source]++;
  if (fanIn[e.target] !== undefined) fanIn[e.target]++;
}

const groupImportsTo = {}; // group -> set of groups it imports from
const groupImportedByFrom = {}; // group -> set of groups that import it
for (const g of Object.keys(directoryGroups)) {
  groupImportsTo[g] = new Set();
  groupImportedByFrom[g] = new Set();
}
for (const e of importEdges) {
  const sg = groupForFile.get(e.source);
  const tg = groupForFile.get(e.target);
  if (sg === undefined || tg === undefined) continue;
  if (sg !== tg) {
    groupImportsTo[sg].add(tg);
    groupImportedByFrom[tg].add(sg);
  }
}

// ---------- D. Cross-Category Dependency Analysis ----------

const crossCategoryMap = new Map(); // key: fromType|toType|edgeType -> count
for (const e of allEdges) {
  if (e.type === 'imports') continue; // imports handled separately, but could overlap categories too
  const sn = nodeById.get(e.source);
  const tn = nodeById.get(e.target);
  if (!sn || !tn) continue;
  const key = `${sn.type}|${tn.type}|${e.type}`;
  crossCategoryMap.set(key, (crossCategoryMap.get(key) || 0) + 1);
}
// also include cross-type imports edges (e.g. file importing something else - unlikely but check)
for (const e of importEdges) {
  const sn = nodeById.get(e.source);
  const tn = nodeById.get(e.target);
  if (!sn || !tn) continue;
  if (sn.type !== tn.type) {
    const key = `${sn.type}|${tn.type}|imports`;
    crossCategoryMap.set(key, (crossCategoryMap.get(key) || 0) + 1);
  }
}

const crossCategoryEdges = [];
for (const [key, count] of crossCategoryMap.entries()) {
  const [fromType, toType, edgeType] = key.split('|');
  crossCategoryEdges.push({ fromType, toType, edgeType, count });
}

// ---------- E. Inter-Group Import Frequency ----------

const interGroupMap = new Map(); // key: from|to -> count
for (const e of importEdges) {
  const sg = groupForFile.get(e.source);
  const tg = groupForFile.get(e.target);
  if (sg === undefined || tg === undefined) continue;
  if (sg === tg) continue;
  const key = `${sg}|${tg}`;
  interGroupMap.set(key, (interGroupMap.get(key) || 0) + 1);
}
const interGroupImports = [];
for (const [key, count] of interGroupMap.entries()) {
  const [from, to] = key.split('|');
  interGroupImports.push({ from, to, count });
}

// ---------- F. Intra-Group Import Density ----------

const intraGroupDensity = {};
for (const g of Object.keys(directoryGroups)) {
  let internalEdges = 0;
  let totalEdges = 0;
  for (const e of importEdges) {
    const sg = groupForFile.get(e.source);
    const tg = groupForFile.get(e.target);
    if (sg !== g && tg !== g) continue;
    totalEdges++;
    if (sg === g && tg === g) internalEdges++;
  }
  intraGroupDensity[g] = {
    internalEdges,
    totalEdges,
    density: totalEdges > 0 ? +(internalEdges / totalEdges).toFixed(3) : 0
  };
}

// ---------- G. Directory Pattern Matching ----------

const DIR_PATTERNS = {
  api: ['routes', 'api', 'controllers', 'endpoints', 'handlers', 'controller', 'routers', 'blueprints', 'serializers'],
  service: ['services', 'core', 'lib', 'domain', 'logic', 'signals', 'internal', 'composables'],
  data: ['models', 'db', 'data', 'persistence', 'repository', 'entities', 'migrations', 'entity', 'sql', 'database', 'schema'],
  ui: ['components', 'views', 'pages', 'ui', 'layouts', 'screens'],
  middleware: ['middleware', 'plugins', 'interceptors', 'guards'],
  utility: ['utils', 'helpers', 'common', 'shared', 'tools', 'templatetags', 'pkg'],
  config: ['config', 'constants', 'env', 'settings', 'management', 'commands'],
  test: ['__tests__', 'test', 'tests', 'spec', 'specs'],
  types: ['types', 'interfaces', 'schemas', 'contracts', 'dtos', 'dto', 'request', 'response'],
  hooks: ['hooks'],
  state: ['store', 'state', 'reducers', 'actions', 'slices'],
  assets: ['assets', 'static', 'public'],
  entry: ['cmd', 'bin'],
  documentation: ['docs', 'documentation', 'wiki'],
  infrastructure: ['deploy', 'deployment', 'infra', 'infrastructure', 'k8s', 'kubernetes', 'helm', 'charts', 'terraform', 'tf', 'docker'],
  'ci-cd': ['.github', '.gitlab', '.circleci']
};

const dirToPattern = {};
for (const [pattern, dirs] of Object.entries(DIR_PATTERNS)) {
  for (const d of dirs) dirToPattern[d] = pattern;
}

const patternMatches = {};
for (const g of Object.keys(directoryGroups)) {
  if (dirToPattern[g]) {
    patternMatches[g] = dirToPattern[g];
  }
}

// ---------- H. Deployment Topology Detection ----------

const infraFiles = [];
let hasDockerfile = false, hasCompose = false, hasK8s = false, hasTerraform = false, hasCI = false;

for (const n of fileNodes) {
  const fp = n.filePath;
  const base = path.basename(fp);
  if (base === 'Dockerfile' || base.startsWith('Dockerfile.')) { hasDockerfile = true; infraFiles.push(fp); }
  if (base.startsWith('docker-compose')) { hasCompose = true; infraFiles.push(fp); }
  if (/\.ya?ml$/.test(base) && /k8s|kubernetes/i.test(fp)) { hasK8s = true; infraFiles.push(fp); }
  if (base.endsWith('.tf') || base.endsWith('.tfvars')) { hasTerraform = true; infraFiles.push(fp); }
  if (fp.includes('.github/workflows') || base === '.gitlab-ci.yml' || base === 'Jenkinsfile') { hasCI = true; infraFiles.push(fp); }
  if (base === 'Makefile') { infraFiles.push(fp); }
}

const deploymentTopology = {
  hasDockerfile,
  hasCompose,
  hasK8s,
  hasTerraform,
  hasCI,
  infraFiles: [...new Set(infraFiles)]
};

// ---------- I. Data Pipeline Detection ----------

const schemaFiles = [];
const migrationFiles = [];
const dataModelFiles = [];
const apiHandlerFiles = [];

for (const n of fileNodes) {
  const fp = n.filePath;
  const base = path.basename(fp);
  if (base.endsWith('.sql') || base.endsWith('.graphql') || base.endsWith('.gql') || base.endsWith('.proto')) {
    schemaFiles.push(fp);
  }
  if (fp.includes('migrations/')) migrationFiles.push(fp);
  const g = groupForFile.get(n.id);
  if (g && DIR_PATTERNS.data.includes(g)) dataModelFiles.push(fp);
  if ((n.tags || []).includes('data-model')) dataModelFiles.push(fp);
  if (g && DIR_PATTERNS.api.includes(g)) apiHandlerFiles.push(fp);
  if ((n.tags || []).includes('api-handler')) apiHandlerFiles.push(fp);
}

const dataPipeline = {
  schemaFiles: [...new Set(schemaFiles)],
  migrationFiles: [...new Set(migrationFiles)],
  dataModelFiles: [...new Set(dataModelFiles)],
  apiHandlerFiles: [...new Set(apiHandlerFiles)]
};

// ---------- J. Documentation Coverage ----------

const docFiles = fileNodes.filter(n => n.type === 'document' || /\.md$|\.rst$/.test(n.filePath));
const groupsWithDocsSet = new Set();
for (const n of fileNodes) {
  if (n.type !== 'document') continue;
  // README at root associates with all groups loosely; specific docs/* don't map directly.
  // We mark a group as documented if a doc file's path stem matches the group name, or if it's a root README.
  const base = path.basename(n.filePath).toLowerCase();
  if (base.startsWith('readme')) {
    for (const g of Object.keys(directoryGroups)) groupsWithDocsSet.add(g);
  }
}
const totalGroups = Object.keys(directoryGroups).length;
const groupsWithDocs = groupsWithDocsSet.size;
const undocumentedGroups = Object.keys(directoryGroups).filter(g => !groupsWithDocsSet.has(g));

const docCoverage = {
  groupsWithDocs,
  totalGroups,
  coverageRatio: totalGroups > 0 ? +(groupsWithDocs / totalGroups).toFixed(2) : 0,
  undocumentedGroups
};

// ---------- K. Dependency Direction ----------

const dependencyDirection = [];
const seenPairs = new Set();
for (const { from, to, count } of interGroupImports) {
  const reverseKey = `${to}|${from}`;
  const key = `${from}|${to}`;
  if (seenPairs.has(key) || seenPairs.has(reverseKey)) continue;
  seenPairs.add(key);
  seenPairs.add(reverseKey);
  const reverseCount = interGroupMap.get(reverseKey) || 0;
  if (count > reverseCount) {
    dependencyDirection.push({ dependent: from, dependsOn: to });
  } else if (reverseCount > count) {
    dependencyDirection.push({ dependent: to, dependsOn: from });
  }
}

// ---------- File Stats ----------

const filesPerGroup = {};
for (const [g, ids] of Object.entries(directoryGroups)) filesPerGroup[g] = ids.length;

const nodeTypeCounts = {};
for (const [t, ids] of Object.entries(nodeTypeGroups)) nodeTypeCounts[t] = ids.length;

const fileStats = {
  totalFileNodes: fileNodes.length,
  filesPerGroup,
  nodeTypeCounts
};

// ---------- Output ----------

const result = {
  scriptCompleted: true,
  directoryGroups,
  nodeTypeGroups,
  crossCategoryEdges,
  interGroupImports,
  intraGroupDensity,
  patternMatches,
  deploymentTopology,
  dataPipeline,
  docCoverage,
  dependencyDirection,
  fileStats,
  fileFanIn: fanIn,
  fileFanOut: fanOut
};

try {
  fs.writeFileSync(outputPath, JSON.stringify(result, null, 2));
} catch (e) {
  fail('Could not write output file: ' + e.message);
}

console.log('Analysis complete. Wrote results to ' + outputPath);
process.exit(0);
