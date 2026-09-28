import { PanelTitle } from "@/shared/ui/PanelTitle";
import { useAppData } from "@/shared/context/AppDataContext";
import { api } from "@/shared/api/base";

export const RulesList = () => {
  const { rules, refresh, setNotice } = useAppData();
  const changeRule = async (ruleId: number, action: "toggle" | "delete") => {
    try {
      await api(`/api/rules/${ruleId}${action === "toggle" ? "/toggle" : ""}`, {
        method: action === "toggle" ? "PATCH" : "DELETE",
      });
      await refresh();
      setNotice(action === "toggle" ? "Состояние правила изменено" : "Правило удалено");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Не удалось изменить правило");
    }
  };

  return (
    <section className="panel">
      <PanelTitle
        title="Сохранённые правила"
        subtitle={`${rules.length} всего`}
      />
      {rules.map((rule) => (
        <div className="rule-row" key={rule.id}>
          <div>
            <strong>{rule.name}</strong>
            <pre>{JSON.stringify(rule.condition)}</pre>
          </div>
          <button onClick={() => void changeRule(rule.id, "toggle")}>
            {rule.enabled ? "Включено" : "Выключено"}
          </button>
          <button onClick={() => void changeRule(rule.id, "delete")}>
            Удалить
          </button>
        </div>
      ))}
    </section>
  );
};
