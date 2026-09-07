import { createContext, useContext, useEffect, useState } from "react";
import {
  GoogleAuthProvider,
  createUserWithEmailAndPassword,
  onAuthStateChanged,
  signInWithEmailAndPassword,
  signInWithPopup,
  signOut as firebaseSignOut,
  updateProfile,
} from "firebase/auth";
import { getFirebaseAuth, isFirebaseConfigured } from "./firebase";
import { setAuthTokenProvider } from "./api";

const AuthContext = createContext(null);

/**
 * Real Firebase Auth, wired end to end: sign in/up/out here call the
 * actual Firebase SDK (getFirebaseAuth() from ./firebase.js), and
 * api.js's requests carry the resulting ID token automatically via
 * setAuthTokenProvider -- no component that calls apiPost/apiGet needs
 * to know auth exists at all.
 *
 * Degrades honestly when Firebase isn't configured (no VITE_FIREBASE_*
 * env vars set): `configured` is false, and every method below throws a
 * clear "Firebase isn't configured yet" error rather than a cryptic
 * Firebase SDK failure -- callers (AuthPage) show that as a real,
 * visible message, same principle as the backend's 503.
 */
export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const configured = isFirebaseConfigured();

  useEffect(() => {
    const auth = getFirebaseAuth();
    if (!auth) {
      setLoading(false);
      return;
    }
    const unsubscribe = onAuthStateChanged(auth, (firebaseUser) => {
      setUser(firebaseUser);
      setLoading(false);
    });
    return unsubscribe;
  }, []);

  useEffect(() => {
    setAuthTokenProvider(async () => {
      const auth = getFirebaseAuth();
      if (!auth?.currentUser) return null;
      return auth.currentUser.getIdToken();
    });
  }, []);

  function _requireAuth() {
    const auth = getFirebaseAuth();
    if (!auth) throw new Error("Firebase isn't configured yet.");
    return auth;
  }

  async function signInWithGoogle() {
    try {
      await signInWithPopup(_requireAuth(), new GoogleAuthProvider());
    } catch (err) {
      // The user closing the popup or opening a second one isn't a real
      // error -- it's just changing their mind. Showing an alarming
      // "sign-in failed" banner for that would be worse than showing
      // nothing at all.
      if (err.code === "auth/popup-closed-by-user" || err.code === "auth/cancelled-popup-request") {
        return;
      }
      if (err.code === "auth/popup-blocked") {
        throw new Error("Your browser blocked the sign-in popup. Please allow popups for this site and try again.");
      }
      if (err.code === "auth/account-exists-with-different-credential") {
        throw new Error("An account already exists with this email using a different sign-in method. Try signing in with email and password instead.");
      }
      throw err;
    }
  }

  async function signInWithEmail(email, password) {
    await signInWithEmailAndPassword(_requireAuth(), email, password);
  }

  async function signUpWithEmail(email, password, name) {
    const auth = _requireAuth();
    const cred = await createUserWithEmailAndPassword(auth, email, password);
    if (name) await updateProfile(cred.user, { displayName: name });
  }

  async function signOutUser() {
    const auth = getFirebaseAuth();
    if (auth) await firebaseSignOut(auth);
  }

  return (
    <AuthContext.Provider value={{ user, loading, configured, signInWithGoogle, signInWithEmail, signUpWithEmail, signOutUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
