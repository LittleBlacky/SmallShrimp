import {create} from "zustand";

interface ServerState {
  status: "stopped" | "starting" | "running" | "error";
  port: number;
  currentAgent: string;
}

interface ServerActions {
  setStatus: (status: ServerState["status"], port?: number) => void;
  setAgent: (agent: string) => void;
  reset: () => void;
}

export const useServerStore = create<ServerState & ServerActions>((set) => ({
  status: "stopped",
  port: 0,
  currentAgent: "pickle",

  setStatus: (status, port) => set({status, port: port ?? 0}),
  setAgent: (agent) => set({currentAgent: agent}),
  reset: () => set({status: "stopped", port: 0}),
}));
