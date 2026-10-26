// App lock: passcode plus Face ID / Touch ID (a passkey). With the lock on, everything Balance Tracker
// keeps on this phone is encrypted (AES-256-GCM) with a random data key, and that key is only ever
// stored wrapped: once by your passcode (PBKDF2-SHA256, 600,000 rounds) and, with Face ID on, once by
// a secret only your passkey can produce (the WebAuthn PRF extension). While locked, the app holds
// neither the key nor your data in memory. Face ID itself never leaves the phone.
import * as C from "./crypto.js";

const KEY = "bt-lock-v1";
const VAULT = "bt-vault-v1";
const LEGACY_ITERATIONS = 150000; // 2.0 stored a PBKDF2 hash of the passcode; it's upgraded on first unlock
export const MIN_PASSCODE = 6;
export const WIPE_AFTER = 10;
const FREE_TRIES = 5;
const PRF_INFO = "BalanceTracker Face ID key v1";

export function cfg() {
  try { return JSON.parse(localStorage.getItem(KEY) || "null"); } catch { return null; }
}
function store(c) { localStorage.setItem(KEY, JSON.stringify(c)); }

/** Is a passcode set? */
export const enabled = () => { const c = cfg(); return !!(c?.pin || c?.pinHash); };
/** Set up by version 2.0: the passcode is right but the data isn't encrypted yet. */
export const legacy = () => { const c = cfg(); return !!c?.pinHash && !c?.pin; };
export const faceIdOn = () => { const c = cfg(); return !!(c?.credId && c?.prf); };
export const lockAfterMinutes = () => cfg()?.after ?? 0;
export const numericPasscode = () => cfg()?.numeric !== false;
export const wipeOn = () => !!cfg()?.wipe;

/** Why a new passcode won't do, or "" if it's fine. */
export function passcodeProblem(pin, numeric) {
  if (numeric && !/^\d+$/.test(pin)) return "Use digits only (or turn on letters and numbers).";
  if (pin.length < MIN_PASSCODE) return `Use at least ${MIN_PASSCODE} ${numeric ? "digits" : "characters"}.`;
  if (pin.length > 64) return "That's too long.";
  const codes = [...pin].map((ch) => ch.codePointAt(0));
  const steps = new Set(codes.slice(1).map((c, i) => c - codes[i]));
  if (steps.size === 1 && [...steps][0] >= -1 && [...steps][0] <= 1) return "That's too easy to guess (like 111111 or 123456).";
  if (["123123", "121212", "112233", "123321", "654321", "696969", "159753", "000000", "password"].includes(pin.toLowerCase())) {
    return "That's one of the most common passcodes — pick another.";
  }
  return "";
}

/** Seconds the user must wait after too many wrong passcodes (0 = can try now). */
export function waitSeconds() {
  const c = cfg();
  return c?.until ? Math.max(0, Math.ceil((c.until - Date.now()) / 1000)) : 0;
}

/**
 * Try a passcode. Resolves to {dek} (the data key) when right; {legacy: true} when it's the right
 * passcode for a 2.0 lock (data not encrypted yet); {wrong: true} otherwise, plus {wiped: true} when
 * "erase after 10 tries" is on and this was the 10th (the caller erases the data).
 */
export async function unlockWithPin(pin) {
  const c = cfg();
  if (!c || waitSeconds() > 0) return { wrong: true };
  let result = null;
  if (c.pin) {
    try {
      const kek = await C.aesKey(await C.deriveBits(pin, C.unb64(c.pin.salt), c.pin.iterations));
      result = { dek: await C.decrypt(kek, c.pin, "lock-pin") };
    } catch { result = null; }
  } else if (c.pinHash) {
    const h = await C.deriveBits(pin, C.unb64(c.salt), LEGACY_ITERATIONS);
    if (C.sameBytes(h, C.unb64(c.pinHash))) result = { legacy: true };
  }
  if (result) { c.fails = 0; c.until = 0; store(c); return result; }
  c.fails = (c.fails || 0) + 1;
  if (c.fails >= FREE_TRIES) c.until = Date.now() + Math.min(15 * 60, 30 * 2 ** (c.fails - FREE_TRIES)) * 1000;
  store(c);
  return c.wipe && c.fails >= WIPE_AFTER ? { wrong: true, wiped: true } : { wrong: true };
}

/** Set (or change) the passcode that wraps the data key `dek` (a new one is made if not given). */
export async function setPasscode(pin, numeric, dek = null) {
  dek = dek || C.randomBytes(32);
  const salt = C.randomBytes(16);
  const kek = await C.aesKey(await C.deriveBits(pin, salt, C.ITERATIONS));
  const box = await C.encrypt(kek, dek, "lock-pin");
  const c = cfg() || { after: 0 };
  delete c.pinHash; delete c.salt; // 2.0's passcode hash isn't needed once the key is wrapped
  if (!c.prf) delete c.credId; // a 2.0 Face ID passkey can't unwrap the key; it has to be turned on again
  store({ ...c, v: 2, numeric: !!numeric, pin: { salt: C.b64(salt), iterations: C.ITERATIONS, ...box }, fails: 0, until: 0 });
  return dek;
}

// ---------------------------------------------------------------- Face ID (passkey + PRF)
export class FaceIdUnsupported extends Error {
  constructor() { super("This iPhone can't use Face ID to unlock encrypted data (it needs iOS 18 or later and iCloud Keychain)."); this.name = "FaceIdUnsupported"; }
}

export async function faceIdAvailable() {
  try {
    return !!(window.PublicKeyCredential && await PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable());
  } catch { return false; }
}

const prfKey = async (secret) => C.aesKey(await C.hkdfBits(new Uint8Array(secret), PRF_INFO));

async function assertion(credId, prfSalt) {
  const res = await navigator.credentials.get({
    publicKey: {
      challenge: C.randomBytes(32),
      rpId: location.hostname,
      allowCredentials: [{ type: "public-key", id: credId, transports: ["internal"] }],
      userVerification: "required",
      timeout: 60000,
      extensions: { prf: { eval: { first: prfSalt } } },
    },
  });
  const flags = new Uint8Array(res.response.authenticatorData)[32];
  if ((flags & 0x04) === 0) return null; // UV bit: the user was verified (Face ID / Touch ID / device passcode)
  return res.getClientExtensionResults?.()?.prf?.results?.first || null;
}

/** Create a passkey and wrap the data key with its PRF secret. Throws FaceIdUnsupported without PRF. */
export async function registerFaceId(dek) {
  const prfSalt = C.randomBytes(32);
  const cred = await navigator.credentials.create({
    publicKey: {
      challenge: C.randomBytes(32),
      rp: { name: "Balance Tracker", id: location.hostname },
      user: { id: C.randomBytes(16), name: "Balance Tracker", displayName: "Balance Tracker lock" },
      pubKeyCredParams: [{ type: "public-key", alg: -7 }, { type: "public-key", alg: -257 }],
      authenticatorSelection: { authenticatorAttachment: "platform", userVerification: "required", residentKey: "preferred" },
      attestation: "none",
      timeout: 60000,
      extensions: { prf: { eval: { first: prfSalt } } },
    },
  });
  const ext = cred.getClientExtensionResults?.()?.prf;
  let secret = ext?.results?.first || null;
  // Some versions only hand over the PRF secret when signing in, so ask once more
  if (!secret && ext?.enabled !== false) secret = await assertion(cred.rawId, prfSalt);
  if (!secret) throw new FaceIdUnsupported();
  const box = await C.encrypt(await prfKey(secret), dek, "lock-faceid");
  store({ ...cfg(), credId: C.b64(cred.rawId), prf: { salt: C.b64(prfSalt), ...box } });
}

/** Ask for Face ID. Resolves to {dek} only if the phone verified the user and the passkey unwrapped the key. */
export async function unlockWithFaceId() {
  const c = cfg();
  if (!c?.credId || !c?.prf) return null;
  const secret = await assertion(C.unb64(c.credId), C.unb64(c.prf.salt));
  if (!secret) return null;
  try {
    const dek = await C.decrypt(await prfKey(secret), c.prf, "lock-faceid");
    const now = cfg();
    now.fails = 0; now.until = 0;
    store(now);
    return { dek };
  } catch { return null; }
}

export function forgetFaceId() { const c = cfg(); if (c) { delete c.credId; delete c.prf; store(c); } }
export function setAfter(min) { const c = cfg(); if (c) { c.after = min; store(c); } }
export function setWipe(on) { const c = cfg(); if (c) { c.wipe = !!on; store(c); } }

// ---------------------------------------------------------------- the encrypted store
export const hasVault = () => localStorage.getItem(VAULT) !== null;
export async function writeVault(key, text) {
  localStorage.setItem(VAULT, JSON.stringify(await C.encrypt(key, text, "vault")));
}
/** The vault's text, or null if there's none. Throws if the key is wrong. */
export async function readVault(key) {
  const raw = localStorage.getItem(VAULT);
  if (raw === null) return null;
  return new TextDecoder().decode(await C.decrypt(key, JSON.parse(raw), "vault"));
}
/** Remove the lock and the encrypted store (the caller has saved the data unencrypted first, or is erasing it). */
export function disable() { localStorage.removeItem(KEY); localStorage.removeItem(VAULT); }
