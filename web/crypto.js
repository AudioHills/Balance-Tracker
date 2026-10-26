// Encryption for the sync file, backups and the app lock: AES-256-GCM, with keys stretched from a
// passphrase by PBKDF2-SHA256 (Web Crypto, so nothing hand-rolled). Encrypted files use the same
// format as balance_tracker/encryption.py; tests/test_web_engine.py checks that each side opens the other's.
export const ITERATIONS = 600000; // OWASP's PBKDF2-SHA256 recommendation
const MIN_ITERATIONS = 100000, MAX_ITERATIONS = 5000000; // refuse files that are trivially weak or would hang
const KINDS = ["sync", "backup"];
const te = new TextEncoder(), td = new TextDecoder();

export function b64(bytes) {
  const a = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let s = "";
  for (let i = 0; i < a.length; i += 0x8000) s += String.fromCharCode(...a.subarray(i, i + 0x8000));
  return btoa(s);
}
export const unb64 = (s) => Uint8Array.from(atob(String(s)), (c) => c.charCodeAt(0));
export const randomBytes = (n) => crypto.getRandomValues(new Uint8Array(n));
const aad = (purpose) => te.encode(`BalanceTracker:${purpose}:v1`);

/** Constant-time comparison of two byte arrays. */
export function sameBytes(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

/** Raw 32-byte key from a passphrase. */
export async function deriveBits(secret, salt, iterations = ITERATIONS) {
  const base = await crypto.subtle.importKey("raw", te.encode(String(secret).normalize("NFC")), "PBKDF2", false, ["deriveBits"]);
  return new Uint8Array(await crypto.subtle.deriveBits({ name: "PBKDF2", hash: "SHA-256", salt, iterations }, base, 256));
}
/** Raw 32-byte key from high-entropy input (e.g. a Face ID passkey's PRF output). */
export async function hkdfBits(input, info) {
  const base = await crypto.subtle.importKey("raw", input, "HKDF", false, ["deriveBits"]);
  return new Uint8Array(await crypto.subtle.deriveBits({ name: "HKDF", hash: "SHA-256", salt: new Uint8Array(32), info: te.encode(info) }, base, 256));
}
export const aesKey = (raw) => crypto.subtle.importKey("raw", raw, "AES-GCM", false, ["encrypt", "decrypt"]);

/** Encrypt bytes or text. `purpose` is bound into the ciphertext, so a blob can't be reused elsewhere. */
export async function encrypt(key, plain, purpose) {
  const iv = randomBytes(12);
  const body = typeof plain === "string" ? te.encode(plain) : plain;
  const ct = await crypto.subtle.encrypt({ name: "AES-GCM", iv, additionalData: aad(purpose) }, key, body);
  return { iv: b64(iv), data: b64(ct) };
}
/** Decrypt to bytes. Throws (OperationError) if the key is wrong or anything was tampered with. */
export async function decrypt(key, box, purpose) {
  return new Uint8Array(await crypto.subtle.decrypt({ name: "AES-GCM", iv: unb64(box.iv), additionalData: aad(purpose) }, key, unb64(box.data)));
}

// ---------------------------------------------------------------- encrypted files
export class WrongPassword extends Error { constructor() { super("Wrong password or passphrase"); this.name = "WrongPassword"; } }

/** Is this parsed JSON an encrypted Balance Tracker file? */
export const isEnvelope = (obj) => !!obj && typeof obj === "object" && obj.app === "BalanceTracker" && obj.encrypted === 1;

function checkEnvelope(env) {
  const it = env.iterations;
  if (!KINDS.includes(env.kind) || env.kdf !== "PBKDF2-SHA256" || env.cipher !== "AES-256-GCM" ||
      !Number.isInteger(it) || it < MIN_ITERATIONS || it > MAX_ITERATIONS) {
    throw new Error("This encrypted file uses settings this version of Balance Tracker doesn't support.");
  }
  if (unb64(env.salt).length < 16 || unb64(env.iv).length !== 12) throw new Error("This encrypted file is damaged.");
}

/** A passphrase-derived key plus the salt and iteration count needed to describe it in a file. */
export async function newFileKey(passphrase, salt = randomBytes(16), iterations = ITERATIONS) {
  const raw = await deriveBits(passphrase, salt, iterations);
  return { salt: b64(salt), iterations, raw: b64(raw), key: await aesKey(raw) };
}
/** Rebuild a stored file key ({salt, iterations, raw}). */
export async function loadFileKey(stored) {
  return { salt: stored.salt, iterations: stored.iterations, raw: stored.raw, key: await aesKey(unb64(stored.raw)) };
}
export const storableKey = (k) => ({ salt: k.salt, iterations: k.iterations, raw: k.raw });

/** Encrypt `text` (a backup or sync file's JSON) into the file format. */
export async function seal(text, fileKey, kind) {
  const box = await encrypt(fileKey.key, text, kind);
  return JSON.stringify({ app: "BalanceTracker", encrypted: 1, kind, kdf: "PBKDF2-SHA256", iterations: fileKey.iterations,
    salt: fileKey.salt, cipher: "AES-256-GCM", iv: box.iv, data: box.data }, null, 1);
}
/** Does `fileKey` belong to the passphrase this file was made with? (Same salt and iterations.) */
export const keyFits = (env, fileKey) => !!fileKey && env.salt === fileKey.salt && env.iterations === fileKey.iterations;

/** Open an encrypted file with a stored key. Throws WrongPassword if it doesn't fit. */
export async function openWithKey(env, fileKey) {
  checkEnvelope(env);
  if (!keyFits(env, fileKey)) throw new WrongPassword();
  try { return td.decode(await decrypt(fileKey.key, env, env.kind)); } catch { throw new WrongPassword(); }
}
/** Open an encrypted file with a passphrase. Returns { text, fileKey } so the key can be remembered. */
export async function openWithPassphrase(env, passphrase) {
  checkEnvelope(env);
  const fileKey = await newFileKey(passphrase, unb64(env.salt), env.iterations);
  return { text: await openWithKey(env, fileKey), fileKey };
}
