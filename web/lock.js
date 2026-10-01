// App lock: Face ID / Touch ID through WebAuthn (passkeys) plus a passcode fallback.
// This is a privacy screen for the app on this device. The passcode is stored only as a
// salted PBKDF2 hash; Face ID never leaves the phone (the browser just reports success).
const KEY = "bt-lock-v1";
const ITER = 150000;

const b64 = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf)));
const unb64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));

export function cfg() {
  try { return JSON.parse(localStorage.getItem(KEY) || "null"); } catch { return null; }
}
function store(c) { localStorage.setItem(KEY, JSON.stringify(c)); }

export const enabled = () => !!cfg()?.pinHash;
export const faceIdOn = () => !!cfg()?.credId;
export const lockAfterMinutes = () => cfg()?.after ?? 0;

async function hashPin(pin, salt) {
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(pin), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits({ name: "PBKDF2", hash: "SHA-256", salt, iterations: ITER }, key, 256);
  return b64(bits);
}

export async function setPin(pin) {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const c = cfg() || { after: 0 };
  store({ ...c, salt: b64(salt), pinHash: await hashPin(pin, salt), fails: 0, until: 0 });
}

/** Seconds the user must wait after too many wrong passcodes (0 = can try now). */
export function waitSeconds() {
  const c = cfg();
  return c?.until ? Math.max(0, Math.ceil((c.until - Date.now()) / 1000)) : 0;
}

export async function checkPin(pin) {
  const c = cfg();
  if (!c?.pinHash || waitSeconds() > 0) return false;
  const ok = (await hashPin(pin, unb64(c.salt))) === c.pinHash;
  if (ok) { c.fails = 0; c.until = 0; }
  else {
    c.fails = (c.fails || 0) + 1;
    if (c.fails >= 5) c.until = Date.now() + Math.min(15 * 60, 30 * 2 ** (c.fails - 5)) * 1000;
  }
  store(c);
  return ok;
}

export async function faceIdAvailable() {
  try {
    return !!(window.PublicKeyCredential && await PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable());
  } catch { return false; }
}

export async function registerFaceId() {
  const cred = await navigator.credentials.create({
    publicKey: {
      challenge: crypto.getRandomValues(new Uint8Array(32)),
      rp: { name: "Balance Tracker", id: location.hostname },
      user: { id: crypto.getRandomValues(new Uint8Array(16)), name: "Balance Tracker", displayName: "Balance Tracker lock" },
      pubKeyCredParams: [{ type: "public-key", alg: -7 }, { type: "public-key", alg: -257 }],
      authenticatorSelection: { authenticatorAttachment: "platform", userVerification: "required", residentKey: "preferred" },
      attestation: "none",
      timeout: 60000,
    },
  });
  const c = cfg();
  store({ ...c, credId: b64(cred.rawId) });
}

/** Ask for Face ID. Resolves true only if the phone verified the user. */
export async function verifyFaceId() {
  const c = cfg();
  if (!c?.credId) return false;
  const res = await navigator.credentials.get({
    publicKey: {
      challenge: crypto.getRandomValues(new Uint8Array(32)),
      rpId: location.hostname,
      allowCredentials: [{ type: "public-key", id: unb64(c.credId), transports: ["internal"] }],
      userVerification: "required",
      timeout: 60000,
    },
  });
  const flags = new Uint8Array(res.response.authenticatorData)[32];
  return (flags & 0x04) !== 0; // UV bit: the user was verified (Face ID / Touch ID / device passcode)
}

export function forgetFaceId() { const c = cfg(); if (c) { delete c.credId; store(c); } }
export function setAfter(min) { const c = cfg(); if (c) { c.after = min; store(c); } }
export function disable() { localStorage.removeItem(KEY); }
