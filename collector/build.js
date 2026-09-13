/**
 * Simple bundler for BotCollector SDK
 * Combines src/*.js into a single standalone UMD bundle in dist/bot-collector.js
 */

const fs = require('fs');
const path = require('path');

const srcDir = path.join(__dirname, 'src');
const distDir = path.join(__dirname, 'dist');

if (!fs.existsSync(distDir)) {
  fs.mkdirSync(distDir, { recursive: true });
}

// Read modules
let fpCode = fs.readFileSync(path.join(srcDir, 'fingerprint.js'), 'utf-8');
let botdCode = fs.readFileSync(path.join(srcDir, 'botd.js'), 'utf-8');
let mouseCode = fs.readFileSync(path.join(srcDir, 'mouse.js'), 'utf-8');
let indexCode = fs.readFileSync(path.join(srcDir, 'index.js'), 'utf-8');

// Strip ES module imports and exports
function stripEsModules(code) {
  return code
    .replace(/import\s+[\s\S]*?from\s+['"][^'"]+['"];?/g, '')
    .replace(/export\s+default\s+[\w$]+;?/g, '')
    .replace(/export\s+(async\s+function|function|class|const|let|var)\s+/g, '$1 ')
    .replace(/export\s+\{[^}]*\};?/g, '');
}

fpCode = stripEsModules(fpCode);
botdCode = stripEsModules(botdCode);
mouseCode = stripEsModules(mouseCode);
indexCode = stripEsModules(indexCode);

const bundle = `(function (global, factory) {
  typeof exports === 'object' && typeof module !== 'undefined' ? module.exports = factory() :
  typeof define === 'function' && define.amd ? define(factory) :
  (global = typeof globalThis !== 'undefined' ? globalThis : global || self, global.BotCollector = factory());
})(this, (function () { 'use strict';

  // --- FingerprintJS Hardware Components ---
${fpCode.split('\n').map(l => '  ' + l).join('\n')}

  // --- BotD Client-Side Heuristics ---
${botdCode.split('\n').map(l => '  ' + l).join('\n')}

  // --- DELBOT Mouse Dynamics Recorder ---
${mouseCode.split('\n').map(l => '  ' + l).join('\n')}

  // --- Unified BotCollector SDK ---
${indexCode.split('\n').map(l => '  ' + l).join('\n')}

  return BotCollector;
}));
`;

const distPath = path.join(distDir, 'bot-collector.js');
fs.writeFileSync(distPath, bundle, 'utf-8');
console.log(`Successfully built ${distPath} (${fs.statSync(distPath).size} bytes)`);
