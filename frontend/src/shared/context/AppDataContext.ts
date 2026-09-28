import { createContext, useContext } from "react";
import type {
  Executor,
  Order,
  Rule,
  Parameter,
  Strategy,
  Analytics,
  Dictionary,
} from "@/shared/types/types";

export interface AppData {
  executors: Executor[];
  orders: Order[];
  rules: Rule[];
  parameters: Parameter[];
  dictionaries: Dictionary[];
  strategy: Strategy;
  analytics: Analytics;
  online: boolean;
  notice: string;
  refresh: () => Promise<void>;
  setNotice: (msg: string) => void;
}

export const AppDataContext = createContext<AppData | null>(null);

export const useAppData = () => {
  const ctx = useContext(AppDataContext);
  if (!ctx) throw new Error("useAppData must be used within AppDataProvider");
  return ctx;
};
