import { useState } from "react";
import { PanelTitle } from "@/shared/ui/PanelTitle";
import { useAppData } from "@/shared/context/AppDataContext";
import { api } from "@/shared/api/base";
import type { Strategy } from "@/shared/types/types";

export const StrategyForm = () => {
  const { strategy: current, setNotice } = useAppData();
  const [strategy, setStrategy] = useState<Strategy>(current);

  const saveStrategy = async () => {
    try {
      await api("/api/strategy", {
        method: "PUT",
        body: JSON.stringify(strategy),
      });
      setNotice("Стратегия сохранена");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Ошибка стратегии");
    }
  };

  return (
    <section className="panel strategy">
      <PanelTitle
        title="Стратегия распределения"
        subtitle="Веса влияют на следующий цикл подбора"
      />
      <label>
        Режим
        <select
          value={strategy.mode}
          onChange={(e) => setStrategy({ ...strategy, mode: e.target.value })}
        >
          <option value="open_load">Баланс открытой нагрузки</option>
          <option value="cumulative_fair">Накопительная справедливость</option>
        </select>
      </label>
      {(["alpha", "beta", "gamma"] as const).map((key) => (
        <label className="slider" key={key}>
          <span>
            {key}: <b>{strategy[key]}</b>
          </span>
          <input
            type="range"
            min="0"
            max="3"
            step="0.05"
            value={strategy[key]}
            onChange={(e) =>
              setStrategy({ ...strategy, [key]: Number(e.target.value) })
            }
          />
        </label>
      ))}
      <div className="formula">
        open_load: α × открытый вес / capacity − γ × бонус · cumulative_fair: +
        β × дневной вес / лимит
      </div>
      <button className="primary" onClick={() => void saveStrategy()}>
        Сохранить стратегию
      </button>
    </section>
  );
};
