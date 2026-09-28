import { useAppData } from "@/shared/context/AppDataContext";
import { PanelTitle } from "@/shared/ui/PanelTitle";
import { ExecutorsTable } from "@/widgets/executors-table/ui/ExecutorsTable";

export const ExecutorsPage = () => {
  const { executors } = useAppData();
  return (
    <section className="panel">
      <PanelTitle
        title="Исполнители"
        subtitle={`${executors.length} записей`}
      />
      <ExecutorsTable executors={executors} />
    </section>
  );
};
