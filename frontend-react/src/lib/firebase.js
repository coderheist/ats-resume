/**
 * Lazily initializes the Firebase app from Vite env vars, mirroring the
 * backend's firebase_auth.py: genuinely optional. If VITE_FIREBASE_*
 * isn't set (no Firebase project configured yet), isFirebaseConfigured()
 * returns false and every auth-dependent UI piece degrades to an honest
 * "not connected" state instead of crashing -- same principle as the
 * backend returning a clear 503 rather than failing to start.
 */
import { initializeApp } from "firebase/app";
import { getAuth } from "firebase/auth";

const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
};

export function isFirebaseConfigured() {
  return Boolean(firebaseConfig.apiKey && firebaseConfig.authDomain && firebaseConfig.projectId && firebaseConfig.appId);
}

let _app = null;
let _auth = null;

export function getFirebaseAuth() {
  if (!isFirebaseConfigured()) return null;
  if (!_auth) {
    _app = initializeApp(firebaseConfig);
    _auth = getAuth(_app);
  }
  return _auth;
}
