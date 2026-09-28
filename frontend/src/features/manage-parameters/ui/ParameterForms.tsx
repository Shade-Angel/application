import { useState } from "react";
import { PanelTitle } from "@/shared/ui/PanelTitle";
import { useAppData } from "@/shared/context/AppDataContext";
import { api } from "@/shared/api/base";

export const ParameterForms = () => {
  const { dictionaries, refresh, setNotice } = useAppData();
  const [param, setParam] = useState({
    entity: "executor",
    key: "",
    label: "",
    data_type: "string",
    dictionary_id: null as number | null,
  });
  const [dictDraft, setDictDraft] = useState({ code: "", label: "" });

  const addParameter = async () => {
    try {
      await api("/api/parameters", {
        method: "POST",
        body: JSON.stringify(param),
      });
      await refresh();
      setParam({ ...param, key: "", label: "", dictionary_id: null });
      setNotice("Параметр добавлен");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Ошибка параметра");
    }
  };

  const addDictionary = async () => {
    try {
      await api("/api/dictionaries", {
        method: "POST",
        body: JSON.stringify(dictDraft),
      });
      await refresh();
      setDictDraft({ code: "", label: "" });
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Ошибка справочника");
    }
  };

  return (
    <section className="panel">
      <PanelTitle title="Новый параметр" subtitle="Добавление без миграции" />
      <label>
        Сущность
        <select
          value={param.entity}
          onChange={(e) => setParam({ ...param, entity: e.target.value })}
        >
          <option value="executor">Исполнитель</option>
          <option value="order">Заявка</option>
        </select>
      </label>
      <label>
        Ключ
        <input
          placeholder="например, languages"
          value={param.key}
          onChange={(e) => setParam({ ...param, key: e.target.value })}
        />
      </label>
      <label>
        Название
        <input
          value={param.label}
          onChange={(e) => setParam({ ...param, label: e.target.value })}
        />
      </label>
      <label>
        Тип
        <select
          value={param.data_type}
          onChange={(e) =>
            setParam({
              ...param,
              data_type: e.target.value,
              dictionary_id: null,
            })
          }
        >
          {["string", "number", "boolean", "date", "enum", "string_array"].map(
            (type) => (
              <option key={type}>{type}</option>
            ),
          )}
        </select>
      </label>
      {["enum", "string_array"].includes(param.data_type) && (
        <label>
          Справочник
          <select
            value={param.dictionary_id ?? ""}
            onChange={(e) =>
              setParam({
                ...param,
                dictionary_id: e.target.value ? Number(e.target.value) : null,
              })
            }
          >
            <option value="">Без справочника</option>
            {dictionaries.map((d) => (
              <option key={d.id} value={d.id}>
                {d.label}
              </option>
            ))}
          </select>
        </label>
      )}
      <button className="primary" onClick={() => void addParameter()}>
        Добавить параметр
      </button>
      <hr />
      <PanelTitle title="Новый справочник" subtitle="enum / string_array" />
      <label>
        Код
        <input
          value={dictDraft.code}
          onChange={(e) => setDictDraft({ ...dictDraft, code: e.target.value })}
        />
      </label>
      <label>
        Название
        <input
          value={dictDraft.label}
          onChange={(e) =>
            setDictDraft({ ...dictDraft, label: e.target.value })
          }
        />
      </label>
      <button onClick={() => void addDictionary()}>Создать справочник</button>
    </section>
  );
};
