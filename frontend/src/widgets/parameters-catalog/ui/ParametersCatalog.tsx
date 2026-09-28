import { PanelTitle } from "@/shared/ui/PanelTitle";
import { useAppData } from "@/shared/context/AppDataContext";
import { api } from "@/shared/api/base";

export const ParametersCatalog = () => {
  const { parameters, dictionaries, refresh } = useAppData();

  const addDictionaryItem = async (dictionaryId: number) => {
    const value = window.prompt("Значение справочника");
    if (!value) return;
    await api(`/api/dictionaries/${dictionaryId}/items`, {
      method: "POST",
      body: JSON.stringify({ value, label: value }),
    });
    await refresh();
  };

  return (
    <section className="panel">
      <PanelTitle
        title="Каталог параметров"
        subtitle={`${parameters.length} полей`}
      />
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Сущность</th>
              <th>Ключ</th>
              <th>Название</th>
              <th>Тип</th>
              <th>Справочник</th>
            </tr>
          </thead>
          <tbody>
            {parameters.map((p) => (
              <tr key={p.id}>
                <td>{p.entity}</td>
                <td>{p.key}</td>
                <td>{p.label}</td>
                <td>{p.data_type}</td>
                <td>
                  {dictionaries.find((d) => d.id === p.dictionary_id)?.label ??
                    "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {dictionaries.map((dictionary) => (
        <div className="rule-row" key={dictionary.id}>
          <div>
            <strong>
              {dictionary.label} ({dictionary.code})
            </strong>
            <pre>
              {dictionary.items
                .map((item) => `${item.value}: ${item.label}`)
                .join(" · ") || "пока пусто"}
            </pre>
          </div>
          <button onClick={() => void addDictionaryItem(dictionary.id)}>
            Добавить значение
          </button>
        </div>
      ))}
    </section>
  );
};
