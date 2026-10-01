#!/usr/bin/env node
/**
 * Minimal, dependency-free runner for Postman v2.1 collections (Node 18+).
 *
 *   node postman/tools/run_collection.mjs \
 *     --collection postman/School-Ops-API.postman_collection.json \
 *     --environment postman/School-Ops-Local.postman_environment.json \
 *     [--folder "06 Fees & invoices"] [--report report.json] [--workdir .]
 *
 * It runs requests in order with their pre-request and test scripts, supporting the subset
 * of the Postman sandbox this collection uses: pm.test, pm.expect, pm.response, pm.request,
 * pm.collectionVariables, pm.environment, pm.variables, pm.execution.skipRequest, pm.info
 * and CryptoJS.HmacSHA512. For everything else, use Postman or Newman.
 */
import { createHmac, randomUUID } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { basename, resolve } from "node:path";

const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, cur, i, all) => (cur.startsWith("--") ? [...acc, [cur.slice(2), all[i + 1]]] : acc), [])
);
if (!args.collection) {
  console.error("Usage: node run_collection.mjs --collection <file> [--environment <file>] [--folder <name>] [--report <file>]");
  process.exit(2);
}
const collection = JSON.parse(readFileSync(args.collection, "utf8"));
const envFile = args.environment ? JSON.parse(readFileSync(args.environment, "utf8")) : { values: [] };
const workdir = resolve(args.workdir || ".");

const collectionVars = new Map((collection.variable || []).map((v) => [v.key, v.value ?? ""]));
const envVars = new Map(envFile.values.filter((v) => v.enabled !== false).map((v) => [v.key, v.value ?? ""]));

// ---------------------------------------------------------------------------- variables
function lookup(name, local) {
  if (name === "$timestamp") return String(Math.floor(Date.now() / 1000));
  if (name === "$randomInt") return String(Math.floor(Math.random() * 1001));
  if (name === "$guid") return randomUUID();
  if (local && local.has(name)) return local.get(name);
  if (envVars.has(name) && envVars.get(name) !== "") return envVars.get(name);
  if (collectionVars.has(name)) return collectionVars.get(name);
  if (envVars.has(name)) return envVars.get(name);
  return undefined;
}
function replaceIn(text, local) {
  if (typeof text !== "string") return text;
  return text.replace(/\{\{([^{}]+)\}\}/g, (m, name) => {
    const value = lookup(name.trim(), local);
    return value === undefined || value === null ? m : String(value);
  });
}

// ---------------------------------------------------------------------------- assertions
function deepEqual(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}
const show = (v) => {
  try { return JSON.stringify(v); } catch { return String(v); }
};
class Assertion {
  constructor(actual, negate = false) { this.actual = actual; this.negate = negate; }
  get to() { return this; } get be() { return this; } get been() { return this; } get have() { return this; }
  get and() { return this; } get that() { return this; } get is() { return this; }
  get not() { return new Assertion(this.actual, !this.negate); }
  get true() { return this._check(this.actual === true, `${show(this.actual)} to be true`); }
  get false() { return this._check(this.actual === false, `${show(this.actual)} to be false`); }
  get ok() { return this._check(Boolean(this.actual), `${show(this.actual)} to be truthy`); }
  _check(cond, message) {
    if (Boolean(cond) === this.negate) throw new Error(`expected ${this.negate ? "NOT " : ""}${message}`);
    return this;
  }
  eql(v) { return this._check(deepEqual(this.actual, v), `${show(this.actual)} to deeply equal ${show(v)}`); }
  equal(v) { return this._check(this.actual === v, `${show(this.actual)} to equal ${show(v)}`); }
  oneOf(list) { return this._check(list.includes(this.actual), `${show(this.actual)} to be one of ${show(list)}`); }
  include(v) {
    const a = this.actual;
    const ok = typeof a === "string" || Array.isArray(a) ? a.includes(v) : a && typeof a === "object" && Object.entries(v).every(([k, x]) => deepEqual(a[k], x));
    return this._check(ok, `${show(a)} to include ${show(v)}`);
  }
  property(name) {
    return this._check(this.actual !== null && typeof this.actual === "object" && Object.prototype.hasOwnProperty.call(this.actual, name), `object to have property ${show(name)}`);
  }
  above(n) { return this._check(this.actual > n, `${show(this.actual)} to be above ${n}`); }
  below(n) { return this._check(this.actual < n, `${show(this.actual)} to be below ${n}`); }
  a(type) {
    const actualType = Array.isArray(this.actual) ? "array" : this.actual === null ? "null" : typeof this.actual;
    return this._check(actualType === type, `${show(this.actual)} to be a ${type}`);
  }
  an(type) { return this.a(type); }
  lengthOf(n) { return this._check(this.actual && this.actual.length === n, `length ${this.actual && this.actual.length} to be ${n}`); }
}

const CryptoJS = {
  HmacSHA512: (message, key) => ({ toString: () => createHmac("sha512", key).update(message).digest("hex") }),
  enc: { Hex: "hex" },
};

// ---------------------------------------------------------------------------- sandbox
function headerList(list) {
  return {
    list,
    get(key) { const h = list.find((x) => x.key.toLowerCase() === key.toLowerCase() && !x.disabled); return h ? h.value : undefined; },
    upsert({ key, value }) { const h = list.find((x) => x.key.toLowerCase() === key.toLowerCase()); if (h) h.value = value; else list.push({ key, value }); },
    add({ key, value }) { list.push({ key, value }); },
  };
}

function runScript(code, ctx) {
  if (!code) return;
  const fn = new Function("pm", "console", "CryptoJS", "postman", code);
  fn(ctx.pm, ctx.console, CryptoJS, {});
}

function makePm(state) {
  return {
    info: { requestName: state.name },
    test(name, fn) {
      try { fn(); state.tests.push({ name, passed: true }); }
      catch (err) { state.tests.push({ name, passed: false, error: err.message }); }
    },
    expect: (v) => new Assertion(v),
    collectionVariables: {
      get: (k) => collectionVars.get(k),
      set: (k, v) => collectionVars.set(k, v === undefined || v === null ? "" : String(v)),
      unset: (k) => collectionVars.set(k, ""),
      has: (k) => collectionVars.has(k) && collectionVars.get(k) !== "",
    },
    environment: {
      get: (k) => envVars.get(k),
      set: (k, v) => envVars.set(k, String(v)),
      unset: (k) => envVars.delete(k),
    },
    variables: {
      get: (k) => lookup(k, state.local),
      set: (k, v) => state.local.set(k, String(v)),
      replaceIn: (t) => replaceIn(t, state.local),
    },
    execution: { skipRequest() { state.skipped = true; } },
    request: state.request,
    get response() { return state.response; },
  };
}

// ---------------------------------------------------------------------------- execution
function scriptOf(item, listen) {
  const ev = (item.event || []).find((e) => e.listen === listen);
  if (!ev) return "";
  return Array.isArray(ev.script.exec) ? ev.script.exec.join("\n") : ev.script.exec || "";
}

function* walk(items, prefix, parents) {
  for (const item of items) {
    const path = `${prefix}/${item.name}`;
    if (item.item) yield* walk(item.item, path, [...parents, item]);
    else yield { item, path, parents };
  }
}

async function execute({ item, path, parents }) {
  const r = item.request;
  const state = {
    name: item.name,
    tests: [],
    local: new Map(),
    skipped: false,
    response: null,
    request: {
      method: r.method,
      url: r.url,
      headers: headerList((r.header || []).map((h) => ({ ...h }))),
      body: r.body ? { ...r.body } : undefined,
      auth: r.auth,
    },
  };
  const pm = makePm(state);
  const ctx = { pm, console: { log: (...a) => state.logs?.push(a.join(" ")), warn: (...a) => state.logs?.push(a.join(" ")) } };
  state.logs = [];

  for (const scope of [collection, ...parents, item]) runScript(scriptOf(scope, "prerequest"), ctx);
  if (state.skipped) return { path, skipped: true, tests: [], logs: state.logs };

  // URL: the raw form, with only enabled query params
  const raw = typeof r.url === "string" ? r.url : r.url.raw;
  const url = replaceIn(raw, state.local);
  const headers = {};
  for (const h of state.request.headers.list) if (!h.disabled) headers[h.key] = replaceIn(h.value, state.local);
  const auth = r.auth || collection.auth;
  if (auth && auth.type === "bearer") {
    const token = replaceIn((auth.bearer.find((b) => b.key === "token") || {}).value || "", state.local);
    headers.Authorization = `Bearer ${token}`;
  }
  let body;
  if (r.body && r.body.mode === "raw") body = replaceIn(state.request.body.raw, state.local);
  if (r.body && r.body.mode === "formdata") {
    body = new FormData();
    for (const f of r.body.formdata) {
      if (f.disabled) continue;
      if (f.type === "file") {
        const file = resolve(workdir, f.src);
        body.append(f.key, new Blob([readFileSync(file)]), basename(file));
      } else body.append(f.key, replaceIn(f.value, state.local));
    }
  }

  const started = Date.now();
  let res;
  try {
    res = await fetch(url, { method: r.method, headers, body, redirect: "manual" });
  } catch (err) {
    return { path, error: `${r.method} ${url}: ${err.message}`, tests: [{ name: "Request sent", passed: false, error: err.message }] };
  }
  const buffer = Buffer.from(await res.arrayBuffer());
  const contentType = res.headers.get("content-type") || "";
  const isText = /json|text|xml|csv/.test(contentType);
  const text = isText ? buffer.toString("utf8") : "";
  state.response = {
    code: res.status,
    status: res.statusText,
    responseTime: Date.now() - started,
    headers: { get: (k) => res.headers.get(k) },
    text: () => text,
    json: () => JSON.parse(text),
  };
  for (const scope of [collection, ...parents, item]) runScript(scriptOf(scope, "test"), ctx);
  return {
    path,
    request: { method: r.method, url },
    response: { code: res.status, status: res.statusText, contentType, body: isText ? text : null, size: buffer.length },
    tests: state.tests,
    logs: state.logs,
  };
}

const results = [];
let failed = 0, passed = 0, skipped = 0, requests = 0;
for (const entry of walk(collection.item, "", [])) {
  if (args.folder && !entry.path.startsWith(`/${args.folder}/`)) continue;
  const result = await execute(entry);
  results.push(result);
  if (result.skipped) { skipped++; console.log(`  ↷ ${entry.path}  (skipped)`); continue; }
  requests++;
  const bad = result.tests.filter((t) => !t.passed);
  failed += bad.length;
  passed += result.tests.length - bad.length;
  const code = result.response ? result.response.code : "ERR";
  console.log(`${bad.length ? "✗" : "✓"} ${code} ${entry.path}`);
  for (const t of bad) console.log(`     ✗ ${t.name}: ${t.error}`);
  if (bad.length && result.response && result.response.body) console.log(`       body: ${result.response.body.slice(0, 300)}`);
}
console.log(`\n${requests} requests, ${skipped} skipped, ${passed} tests passed, ${failed} failed`);
if (args.report) writeFileSync(args.report, JSON.stringify({ executions: results }, null, 2));
process.exit(failed ? 1 : 0);
