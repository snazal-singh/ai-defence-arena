#!/usr/bin/env node
'use strict';

function fail(msg) {
  console.error('ERROR: ' + msg);
  process.exit(1);
}

const inputPath = process.argv[2];
const outputPath = process.argv[3];
if (!inputPath || !outputPath) {
  fail('Usage: node ua-tour-analyze.js <input.json> <output.json>');
}

const fs = require('fs');
const path = require('path');

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
  fail('Invalid JSON in input file: ' + e.message);
}

const nodes = Array.isArray(data.nodes) ? data.nodes : [];
const edges = Array.isArray(data.edges) ? data.edges : [];
const layers = Array.isArray(data.layers) ? data.layers : [];

if (nodes.length === 0) {
  fail('No nodes found in input');
}

// Restrict analysis to "file-level" nodes (file/document/service/pipeline/table/schema/resource/endpoint/config)
// but keep all nodes for index purposes. We treat all provided nodes as the graph's node set.
const nodeById = new Map();
for (const n of nodes) {
  nodeById.set(n.id, n);
}

// ---------- Fan-in / Fan-out ----------
const fanIn = new Map();
const fanOut = new Map();
for (const n of nodes) {
  fanIn.set(n.id, 0);
  fanOut.set(n.id, 0);
}

// Only count edges between known nodes (skip edges pointing to symbol-level nodes not in our node set,
// since this tour's node set is file-level; but if symbol-level edges exist, count them only if both ends exist)
const adjForward = new Map(); // nodeId -> Set of target nodeIds (only edges where both ends are in nodeById)
for (const n of nodes) adjForward.set(n.id, new Set());

for (const e of edges) {
  if (!e || !e.source || !e.target) continue;
  const srcExists = nodeById.has(e.source);
  const tgtExists = nodeById.has(e.target);
  if (srcExists && tgtExists) {
    fanOut.set(e.source, (fanOut.get(e.source) || 0) + 1);
    fanIn.set(e.target, (fanIn.get(e.target) || 0) + 1);
    adjForward.get(e.source).add(e.target);
  }
}

function topN(map, n, keyName) {
  const arr = Array.from(map.entries()).map(([id, val]) => {
    const node = nodeById.get(id) || {};
    return { id, [keyName]: val, name: node.name || id };
  });
  arr.sort((a, b) => b[keyName] - a[keyName]);
  return arr.slice(0, n);
}

const fanInRanking = topN(fanIn, 20, 'fanIn');
const fanOutRanking = topN(fanOut, 20, 'fanOut');

// ---------- Entry Point Candidates ----------
const ENTRY_FILENAMES = new Set([
  'index.ts', 'index.js', 'main.ts', 'main.js', 'app.ts', 'app.js', 'server.ts', 'server.js',
  'mod.rs', 'main.go', 'main.py', 'main.rs', 'manage.py', 'app.py', 'wsgi.py', 'asgi.py',
  'run.py', '__main__.py', 'Application.java', 'Main.java', 'Program.cs', 'config.ru',
  'index.php', 'App.swift', 'Application.kt', 'main.cpp', 'main.c'
]);

const fanOutValues = Array.from(fanOut.values()).filter(v => v > 0 || true);
const sortedFanOutDesc = [...fanOutValues].sort((a, b) => b - a);
const fanOutTop10PctIdx = Math.max(0, Math.floor(sortedFanOutDesc.length * 0.1) - 1);
const fanOutTop10PctThreshold = sortedFanOutDesc.length ? sortedFanOutDesc[fanOutTop10PctIdx] : 0;

const fanInValues = Array.from(fanIn.values());
const sortedFanInAsc = [...fanInValues].sort((a, b) => a - b);
const fanInBottom25PctIdx = Math.min(sortedFanInAsc.length - 1, Math.floor(sortedFanInAsc.length * 0.25));
const fanInBottom25PctThreshold = sortedFanInAsc.length ? sortedFanInAsc[fanInBottom25PctIdx] : 0;

function pathDepth(filePath) {
  if (!filePath) return 99;
  const parts = filePath.split('/').filter(Boolean);
  return parts.length; // 1 = root file, 2 = one level deep
}

const entryScores = [];
for (const n of nodes) {
  let score = 0;
  const fp = n.filePath || '';
  const baseName = n.name || path.basename(fp);

  if (n.type === 'document') {
    const isRoot = pathDepth(fp) === 1;
    const isReadme = /^readme\.md$/i.test(baseName);
    if (isReadme && isRoot) {
      score += 5;
    } else if (isRoot && /\.md$/i.test(baseName)) {
      score += 2;
    }
  } else if (n.type === 'file') {
    if (ENTRY_FILENAMES.has(baseName)) {
      score += 3;
    }
    const depth = pathDepth(fp);
    if (depth <= 2) {
      score += 1;
    }
    const fo = fanOut.get(n.id) || 0;
    if (fo >= fanOutTop10PctThreshold && fo > 0) {
      score += 1;
    }
    const fi = fanIn.get(n.id) || 0;
    if (fi <= fanInBottom25PctThreshold) {
      score += 1;
    }
  }

  if (score > 0) {
    entryScores.push({ id: n.id, score, name: n.name, summary: n.summary });
  }
}
entryScores.sort((a, b) => b.score - a.score);
const entryPointCandidates = entryScores.slice(0, 5);

// ---------- BFS from top CODE entry point ----------
// Skip documentation nodes for BFS start; find top-scoring 'file' type candidate
let bfsStart = null;
for (const c of entryScores) {
  const node = nodeById.get(c.id);
  if (node && node.type === 'file') {
    bfsStart = c.id;
    break;
  }
}
// Fallback: any file node with highest fan-out
if (!bfsStart) {
  const fileNodes = nodes.filter(n => n.type === 'file');
  if (fileNodes.length) {
    fileNodes.sort((a, b) => (fanOut.get(b.id) || 0) - (fanOut.get(a.id) || 0));
    bfsStart = fileNodes[0].id;
  }
}

const bfsTraversal = { startNode: bfsStart, order: [], depthMap: {}, byDepth: {} };

if (bfsStart) {
  const visited = new Set([bfsStart]);
  const queue = [[bfsStart, 0]];
  bfsTraversal.depthMap[bfsStart] = 0;
  while (queue.length) {
    const [cur, depth] = queue.shift();
    bfsTraversal.order.push(cur);
    if (!bfsTraversal.byDepth[depth]) bfsTraversal.byDepth[depth] = [];
    bfsTraversal.byDepth[depth].push(cur);

    const neighbors = adjForward.get(cur) || new Set();
    for (const nb of neighbors) {
      if (!visited.has(nb)) {
        visited.add(nb);
        bfsTraversal.depthMap[nb] = depth + 1;
        queue.push([nb, depth + 1]);
      }
    }
  }
}

// ---------- Non-Code File Inventory ----------
const nonCodeFiles = {
  documentation: [],
  infrastructure: [],
  data: [],
  config: []
};

for (const n of nodes) {
  if (n.type === 'document') {
    nonCodeFiles.documentation.push({ id: n.id, name: n.name, summary: n.summary });
  } else if (n.type === 'service' || n.type === 'pipeline' || n.type === 'resource') {
    nonCodeFiles.infrastructure.push({ id: n.id, name: n.name, type: n.type, summary: n.summary });
  } else if (n.type === 'table' || n.type === 'schema' || n.type === 'endpoint') {
    nonCodeFiles.data.push({ id: n.id, name: n.name, type: n.type, summary: n.summary });
  } else if (n.type === 'config') {
    nonCodeFiles.config.push({ id: n.id, name: n.name, summary: n.summary });
  }
}

// ---------- Tightly Coupled Clusters ----------
// Build bidirectional pairs based on imports/calls edges
const edgeKey = (a, b) => a + '||' + b;
const directedPairs = new Set();
for (const e of edges) {
  if (!e || !e.source || !e.target) continue;
  if (!nodeById.has(e.source) || !nodeById.has(e.target)) continue;
  if (e.type === 'imports' || e.type === 'calls') {
    directedPairs.add(edgeKey(e.source, e.target));
  }
}

const bidirectionalPairs = [];
for (const key of directedPairs) {
  const [a, b] = key.split('||');
  if (a < b) {
    if (directedPairs.has(edgeKey(a, b)) && directedPairs.has(edgeKey(b, a))) {
      bidirectionalPairs.push([a, b]);
    }
  }
}

// Build initial clusters from bidirectional pairs, then expand
const clusterList = [];
const usedInCluster = new Set();

for (const [a, b] of bidirectionalPairs) {
  if (usedInCluster.has(a) || usedInCluster.has(b)) continue;
  const clusterSet = new Set([a, b]);
  usedInCluster.add(a);
  usedInCluster.add(b);

  // Expand: add nodes connecting to 2+ existing cluster members, up to size 5
  let expanded = true;
  while (expanded && clusterSet.size < 5) {
    expanded = false;
    for (const n of nodes) {
      if (clusterSet.has(n.id) || usedInCluster.has(n.id)) continue;
      let connections = 0;
      for (const member of clusterSet) {
        if (adjForward.get(n.id)?.has(member) || adjForward.get(member)?.has(n.id)) {
          connections++;
        }
      }
      if (connections >= 2) {
        clusterSet.add(n.id);
        usedInCluster.add(n.id);
        expanded = true;
        if (clusterSet.size >= 5) break;
      }
    }
  }

  // Count edges within cluster
  let edgeCount = 0;
  for (const e of edges) {
    if (clusterSet.has(e.source) && clusterSet.has(e.target) && e.source !== e.target) {
      edgeCount++;
    }
  }

  clusterList.push({ nodes: Array.from(clusterSet), edgeCount });
}

clusterList.sort((a, b) => b.edgeCount - a.edgeCount);
const clusters = clusterList.slice(0, 10);

// ---------- Layers ----------
const layersOut = {
  count: layers.length,
  list: layers.map(l => ({ id: l.id, name: l.name, description: l.description }))
};

// ---------- Node Summary Index ----------
const nodeSummaryIndex = {};
for (const n of nodes) {
  nodeSummaryIndex[n.id] = { name: n.name, type: n.type, summary: n.summary };
}

// ---------- Output ----------
const result = {
  scriptCompleted: true,
  entryPointCandidates,
  fanInRanking,
  fanOutRanking,
  bfsTraversal,
  nonCodeFiles,
  clusters,
  layers: layersOut,
  nodeSummaryIndex,
  totalNodes: nodes.length,
  totalEdges: edges.length
};

try {
  fs.writeFileSync(outputPath, JSON.stringify(result, null, 2));
} catch (e) {
  fail('Could not write output file: ' + e.message);
}

console.log('Analysis complete. Wrote results to ' + outputPath);
process.exit(0);
