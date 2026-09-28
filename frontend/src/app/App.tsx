import { useState } from "react";
import { useAppData } from "@/shared/context/AppDataContext";
import { downloadExport } from "@/shared/api/base";
import type { Page } from "@/shared/types/types";
import { OrdersPage } from "@/pages/orders/ui/OrdersPage";
import { ExecutorsPage } from "@/pages/executors/ui/ExecutorsPage";
import { RulesPage } from "@/pages/rules/ui/RulesPage";
import { ParametersPage } from "@/pages/parameters/ui/ParametersPage";
import { StrategyPage } from "@/pages/strategy/ui/StrategyPage";
import { AuditPage } from "@/pages/audit/ui/AuditPage";
import { DashboardPage } from "@/pages/dashboard/ui/DashBoardPage";
import { SimulatorPage } from "@/pages/simalator/ui/SimulatorPage";

export const App = () => {
  const [page, setPage] = useState<Page>("Обзор");
  const { online, notice, setNotice } = useAppData();
  const nav: Page[] = [
    "Обзор",
    "Заявки",
    "Исполнители",
    "Правила",
    "Параметры",
    "Стратегия",
    "Симулятор",
    "Audit / DLQ",
  ];

  return (
    <div className="shell">
      <aside>
        <div className="brand">
          EB<span>●</span>
        </div>
        <nav>
          {nav.map((item) => (
            <button
              key={item}
              className={page === item ? "nav active" : "nav"}
              onClick={() => setPage(item)}
            >
              {item}
            </button>
          ))}
        </nav>
        <div className="connection">
          <i className={online ? "green" : "red"} />
          {online ? "Сервис онлайн" : "Нет соединения"}
        </div>
        <a className="docs-link" href="/docs">
          Документация API ↗
        </a>
      </aside>
      <main>
        <header>
          <div>
            <small>ОПЕРАЦИОННЫЙ ЦЕНТР</small>
            <h1>{page === "Обзор" ? "Балансировщик заявок" : page}</h1>
          </div>
          <button
            className="button"
            onClick={() =>
              void downloadExport().catch((error) =>
                setNotice(
                  error instanceof Error ? error.message : "Ошибка экспорта",
                ),
              )
            }
          >
            Экспорт в Excel ↓
          </button>
        </header>
        {notice && <div className="notice">{notice}</div>}
        {page === "Обзор" && <DashboardPage />}
        {page === "Заявки" && <OrdersPage />}
        {page === "Исполнители" && <ExecutorsPage />}
        {page === "Правила" && <RulesPage />}
        {page === "Параметры" && <ParametersPage />}
        {page === "Стратегия" && <StrategyPage />}
        {page === "Симулятор" && <SimulatorPage />}
        {page === "Audit / DLQ" && <AuditPage />}
      </main>
    </div>
  );
};
