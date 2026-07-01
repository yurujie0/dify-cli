// Extract frontend node defaultValue objects via static AST evaluation.
// No runtime imports — we parse each default.ts with the TypeScript compiler,
// locate the `defaultValue` property of the exported `nodeDefault`, and
// evaluate it as a pure literal (enums → their string values).
//
// Usage: node cli/scripts/extract_defaults.mjs <output.json> [dsl_version]
import ts from 'typescript'
import { readdirSync, existsSync, readFileSync, writeFileSync } from 'node:fs'
import * as path from 'node:path'
import * as url from 'node:url'

const __dirname = path.dirname(url.fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '../..')
const WEB = path.join(ROOT, 'web')
const NODES_DIR = path.join(WEB, 'app/components/workflow/nodes')
const OUT = process.argv[2] || path.join(__dirname, '..', 'dify_cli', 'schemas', 'defaults-v0.5.0.json')
const DSL_VERSION = process.argv[3] || '0.5.0'

// Read BlockEnum values from types.ts so we can resolve enum member access
// like BlockEnum.LLM → 'llm'. We parse types.ts once and collect enum defs.
const enums = {
  ...parseEnums(path.join(WEB, 'app/components/workflow/types.ts')),
  ...parseEnums(path.join(WEB, 'types/app.ts')),
  ...parseEnums(path.join(WEB, 'app/components/workflow/block-selector/types.ts')),
}

// Global const-objects (e.g. DATASET_DEFAULT is an object, not enum — handle separately)
const globalConstObjects = {}
Object.assign(globalConstObjects, parseConstObjects(path.join(WEB, 'config/index.ts'), { enums, functions: {}, consts: {}, constObjects: globalConstObjects }))

function parseEnums(filePath) {
  const result = {}
  if (!existsSync(filePath)) return result
  const src = ts.createSourceFile(filePath, readFileSync(filePath, 'utf8'), ts.ScriptTarget.Latest, true)
  for (const stmt of src.statements) {
    if (ts.isEnumDeclaration(stmt)) {
      const name = stmt.name.text
      const members = {}
      let autoIdx = 0
      for (const m of stmt.members) {
        const memberName = m.name && ts.isIdentifier(m.name) ? m.name.text : null
        if (!memberName) continue
        let val = memberName
        if (m.initializer) {
          const ev = evalLiteralNode(m.initializer, { enums: {}, functions: {}, consts: {} })
          if (ev.ok) val = ev.value
          else if (m.initializer.kind === ts.SyntaxKind.NumericLiteral) val = Number(m.initializer.text)
        } else {
          val = autoIdx
          autoIdx++
          continue
        }
        members[memberName] = val
        autoIdx = typeof val === 'number' ? val + 1 : autoIdx
      }
      result[name] = members
    }
  }
  return result
}

function parsePureFunctions(filePath, ctx) {
  const result = {}
  if (!existsSync(filePath)) return result
  const src = ts.createSourceFile(filePath, readFileSync(filePath, 'utf8'), ts.ScriptTarget.Latest, true)
  for (const stmt of src.statements) {
    if (!ts.isVariableStatement(stmt)) continue
    for (const decl of stmt.declarationList.declarations) {
      if (!decl.name || !ts.isIdentifier(decl.name)) continue
      if (!decl.initializer) continue
      if (ts.isArrowFunction(decl.initializer)) {
        const body = decl.initializer.body
        let expr = body
        if (ts.isBlock(body)) {
          for (const s of body.statements) {
            if (ts.isReturnStatement(s) && s.expression) { expr = s.expression; break }
          }
        }
        if (expr) {
          const ev = evalLiteralNode(expr, { ...ctx, functions: { ...ctx.functions, ...result } })
          if (ev.ok) result[decl.name.text] = expr
        }
      }
    }
  }
  return result
}

function parseConstStrings(filePath) {
  const result = {}
  if (!existsSync(filePath)) return result
  const src = ts.createSourceFile(filePath, readFileSync(filePath, 'utf8'), ts.ScriptTarget.Latest, true)
  for (const stmt of src.statements) {
    if (!ts.isVariableStatement(stmt)) continue
    for (const decl of stmt.declarationList.declarations) {
      if (!decl.name || !ts.isIdentifier(decl.name)) continue
      if (!decl.initializer) continue
      if (ts.isStringLiteral(decl.initializer)) result[decl.name.text] = decl.initializer.text
      else if (decl.initializer.kind === ts.SyntaxKind.NumericLiteral) result[decl.name.text] = Number(decl.initializer.text)
      else if (decl.initializer.kind === ts.SyntaxKind.TrueKeyword) result[decl.name.text] = true
      else if (decl.initializer.kind === ts.SyntaxKind.FalseKeyword) result[decl.name.text] = false
    }
  }
  return result
}

// Parse `export const X = { ...pure literal... }` so we can resolve
// DATASET_DEFAULT.top_k style accesses.
function parseConstObjects(filePath, ctx) {
  const result = {}
  if (!existsSync(filePath)) return result
  const src = ts.createSourceFile(filePath, readFileSync(filePath, 'utf8'), ts.ScriptTarget.Latest, true)
  for (const stmt of src.statements) {
    if (!ts.isVariableStatement(stmt)) continue
    for (const decl of stmt.declarationList.declarations) {
      if (!decl.name || !ts.isIdentifier(decl.name)) continue
      if (!decl.initializer || !ts.isObjectLiteralExpression(decl.initializer)) continue
      const ev = evalLiteralNode(decl.initializer, ctx || { enums: {}, functions: {}, consts: result })
      if (ev.ok) result[decl.name.text] = ev.value
    }
  }
  return result
}

function evalLiteralNode(node, ctx) {
  const knownEnums = ctx.enums || {}
  const knownFunctions = ctx.functions || {}
  const knownConsts = ctx.consts || {}
  const knownConstObjects = ctx.constObjects || {}
  if (ts.isParenthesizedExpression(node)) {
    return evalLiteralNode(node.expression, ctx)
  }
  if (ts.isStringLiteral(node)) return { ok: true, value: node.text }
  if (ts.isNumericLiteral(node)) return { ok: true, value: Number(node.text) }
  if (node.kind === ts.SyntaxKind.TrueKeyword) return { ok: true, value: true }
  if (node.kind === ts.SyntaxKind.FalseKeyword) return { ok: true, value: false }
  if (node.kind === ts.SyntaxKind.NullKeyword) return { ok: true, value: null }
  if (node.kind === ts.SyntaxKind.UndefinedKeyword) return { ok: true, value: undefined }
  if (ts.isObjectLiteralExpression(node)) {
    const obj = {}
    for (const prop of node.properties) {
      if (ts.isSpreadAssignment(prop)) {
        const spread = evalLiteralNode(prop.expression, ctx)
        if (!spread.ok) return spread
        if (typeof spread.value !== 'object' || spread.value === null) {
          return { ok: false, reason: 'spread-non-object' }
        }
        Object.assign(obj, spread.value)
        continue
      }
      if (!ts.isPropertyAssignment(prop)) return { ok: false, reason: 'non-property-assignment' }
      const key = prop.name && ts.isIdentifier(prop.name) ? prop.name.text
        : (ts.isStringLiteral(prop.name) ? prop.name.text : null)
      if (!key) return { ok: false, reason: 'bad-key' }
      const v = evalLiteralNode(prop.initializer, ctx)
      if (!v.ok) return v
      obj[key] = v.value
    }
    return { ok: true, value: obj }
  }
  if (ts.isArrayLiteralExpression(node)) {
    const arr = []
    for (const el of node.elements) {
      if (el.kind === ts.SyntaxKind.SpreadElement) {
        const spread = evalLiteralNode(el.expression, ctx)
        if (!spread.ok) return spread
        if (!Array.isArray(spread.value)) return { ok: false, reason: 'array-spread-non-array' }
        arr.push(...spread.value)
        continue
      }
      const v = evalLiteralNode(el, ctx)
      if (!v.ok) return v
      arr.push(v.value)
    }
    return { ok: true, value: arr }
  }
  if (ts.isAsExpression(node) || ts.isTypeAssertionExpression(node)) {
    return evalLiteralNode(node.expression, ctx)
  }
  if (ts.isSpreadElement(node)) {
    return evalLiteralNode(node.expression, ctx)
  }
  if (ts.isPropertyAccessExpression(node)) {
    if (node.expression && ts.isIdentifier(node.expression)) {
      const base = node.expression.text
      const member = node.name.text
      const en = knownEnums[base]
      if (en && member in en) return { ok: true, value: en[member] }
      const co = knownConstObjects[base]
      if (co && typeof co === 'object' && member in co) return { ok: true, value: co[member] }
    }
    return { ok: false, reason: `unresolved-enum-access: ${node.expression?.text}.${node.name.text}` }
  }
  if (ts.isIdentifier(node)) {
    if (node.text === 'undefined') return { ok: true, value: undefined }
    if (node.text in knownConsts) return { ok: true, value: knownConsts[node.text] }
    for (const en of Object.values(knownEnums)) {
      if (node.text in en) return { ok: true, value: en[node.text] }
    }
    return { ok: false, reason: `unresolved-identifier: ${node.text}` }
  }
  if (ts.isCallExpression(node)) {
    // Resolve pure arrow-function calls like getDefaultScheduleConfig()
    // and createWebhookRawVariable() by finding their definition.
    const callee = node.expression
    if (ts.isIdentifier(callee)) {
      const fn = knownFunctions[callee.text]
      if (fn) {
        // fn is the arrow function body expression
        return evalLiteralNode(fn, ctx)
      }
    }
    return { ok: false, reason: `unresolved-call: ${callee.text}` }
  }
  return { ok: false, reason: `unsupported-node: ${ts.SyntaxKind[node.kind]}` }
}

// Find the exported `nodeDefault` const and return its defaultValue property AST.
function findDefaultValueNode(srcFile) {
  for (const stmt of srcFile.statements) {
    if (!ts.isVariableStatement(stmt)) continue
    for (const decl of stmt.declarationList.declarations) {
      if (!decl.name || !ts.isIdentifier(decl.name)) continue
      if (decl.name.text !== 'nodeDefault') continue
      if (!decl.initializer || !ts.isObjectLiteralExpression(decl.initializer)) continue
      for (const prop of decl.initializer.properties) {
        if (!ts.isPropertyAssignment(prop)) continue
        if (prop.name && ts.isIdentifier(prop.name) && prop.name.text === 'defaultValue') {
          return prop.initializer
        }
      }
    }
  }
  return null
}

function findMetaDataTypeNode(srcFile) {
  for (const stmt of srcFile.statements) {
    if (!ts.isVariableStatement(stmt)) continue
    for (const decl of stmt.declarationList.declarations) {
      if (!decl.name || !ts.isIdentifier(decl.name)) continue
      if (decl.name.text !== 'metaData') continue
      if (!decl.initializer) continue
      // metaData is genNodeMetaData({...}) — find type property
      if (ts.isCallExpression(decl.initializer)) {
        const arg = decl.initializer.arguments[0]
        if (arg && ts.isObjectLiteralExpression(arg)) {
          for (const prop of arg.properties) {
            if (ts.isPropertyAssignment(prop) && prop.name && ts.isIdentifier(prop.name) && prop.name.text === 'type') {
              return prop.initializer
            }
          }
        }
      }
    }
  }
  return null
}

const nodeDirs = readdirSync(NODES_DIR).filter(d =>
  existsSync(path.join(NODES_DIR, d, 'default.ts')),
)

const result = {}
const skipped = []

for (const dir of nodeDirs) {
  const fp = path.join(NODES_DIR, dir, 'default.ts')
  try {
    const src = ts.createSourceFile(fp, readFileSync(fp, 'utf8'), ts.ScriptTarget.Latest, true)
    const localEnums = { ...enums }
    const typesTs = path.join(NODES_DIR, dir, 'types.ts')
    if (existsSync(typesTs)) Object.assign(localEnums, parseEnums(typesTs))
    for (const extra of ['constants.ts', 'types.ts']) {
      const ep = path.join(NODES_DIR, dir, extra)
      if (existsSync(ep)) Object.assign(localEnums, parseEnums(ep))
    }
    const localFns = {}
    const localConsts = {}
    const parseFile = (ep) => {
      if (!existsSync(ep)) return
      Object.assign(localConsts, parseConstStrings(ep))
      Object.assign(localFns, parsePureFunctions(ep, { enums: localEnums, functions: localFns, consts: localConsts, constObjects: globalConstObjects }))
    }
    for (const sibling of ['constants.ts', 'types.ts']) {
      parseFile(path.join(NODES_DIR, dir, sibling))
    }
    const utilsDir = path.join(NODES_DIR, dir, 'utils')
    if (existsSync(utilsDir)) {
      for (const u of readdirSync(utilsDir)) {
        if (u.endsWith('.ts')) parseFile(path.join(utilsDir, u))
      }
    }
    const ctx = { enums: localEnums, functions: localFns, consts: localConsts, constObjects: globalConstObjects }

    const dvNode = findDefaultValueNode(src)
    if (!dvNode) { skipped.push(`${dir} (no defaultValue)`); continue }
    const ev = evalLiteralNode(dvNode, ctx)
    if (!ev.ok) { skipped.push(`${dir} (${ev.reason})`); continue }

    const typeNode = findMetaDataTypeNode(src)
    if (!typeNode) { skipped.push(`${dir} (no metaData.type)`); continue }
    const typeEv = evalLiteralNode(typeNode, ctx)
    if (!typeEv.ok) { skipped.push(`${dir} (metaData.type: ${typeEv.reason})`); continue }

    result[typeEv.value] = ev.value
  } catch (e) {
    skipped.push(`${dir} (${e?.message || String(e)})`)
  }
}

const bundle = { dsl_version: DSL_VERSION, node_defaults: result, skipped }
writeFileSync(OUT, JSON.stringify(bundle, null, 2))
console.error(`Wrote ${OUT} (node_defaults=${Object.keys(result).length}, skipped=${skipped.length})`)
if (skipped.length) console.error(`Skipped: ${skipped.join(', ')}`)
