import { create } from "zustand";
import { api, getToken, setToken } from "./api";
import type { User } from "./types";

export type OrbState = "idle" | "listening" | "thinking" | "speaking";

type Store = {
  user: User | null;
  booting: boolean;
  orb: OrbState;
  level: number; // 0..1 audio level driving the orb
  setOrb: (s: OrbState) => void;
  setLevel: (n: number) => void;
  boot: () => Promise<void>;
  login: (token: string, user: User) => void;
  logout: () => void;
  setUser: (u: User) => void;
};

export const useStore = create<Store>((set) => ({
  user: null,
  booting: true,
  orb: "idle",
  level: 0,
  setOrb: (orb) => set({ orb }),
  setLevel: (level) => set({ level }),
  boot: async () => {
    if (!getToken()) return set({ booting: false });
    try {
      const user = await api<User>("/api/auth/me");
      set({ user, booting: false });
    } catch {
      setToken(null);
      set({ user: null, booting: false });
    }
  },
  login: (token, user) => {
    setToken(token);
    set({ user });
  },
  logout: () => {
    setToken(null);
    set({ user: null });
  },
  setUser: (user) => set({ user }),
}));

window.addEventListener("astra:logout", () => useStore.setState({ user: null }));
