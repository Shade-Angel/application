import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useAppData } from "@/shared/context/AppDataContext";

export const TimelineChart = () => {
  const { analytics } = useAppData();
  return (
    <section className="panel">
      <div className="panel-title">
        <div>
          <small>ПОСЛЕДНИЕ 15 МИНУТ</small>
          <h2>Входящие и назначенные заявки</h2>
        </div>
        <span>Обновление по WebSocket</span>
      </div>
      <div className="chart">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={analytics.timeline_15m ?? []}>
            <CartesianGrid strokeDasharray="3 3" stroke="#253345" />
            <XAxis
              dataKey="bucket"
              stroke="#8695a8"
              tickFormatter={(value) =>
                new Date(value).toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                })
              }
            />
            <YAxis stroke="#8695a8" />
            <Tooltip
              contentStyle={{
                background: "#101b29",
                border: "1px solid #29394d",
              }}
            />
            <Bar dataKey="rps_in" name="Входящие" fill="#5578d6" />
            <Bar dataKey="rps_assigned" name="Назначенные" fill="#55d6ad" />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
};

export const LoadChart = () => {
  const { executors } = useAppData();
  return (
    <section className="panel">
      <div className="panel-title">
        <div>
          <small>ТЕКУЩАЯ НАГРУЗКА</small>
          <h2>Открытые заявки по исполнителям</h2>
        </div>
        <span>open weight / capacity</span>
      </div>
      <div className="chart">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={executors.slice(0, 30)}>
            <CartesianGrid strokeDasharray="3 3" stroke="#253345" />
            <XAxis dataKey="id" stroke="#8695a8" />
            <YAxis stroke="#8695a8" />
            <Tooltip
              contentStyle={{
                background: "#101b29",
                border: "1px solid #29394d",
              }}
            />
            <Bar
              dataKey="open_weight"
              name="Открытый вес"
              fill="#55d6ad"
              radius={[4, 4, 0, 0]}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
};
