import { Card, Typography } from "antd";

type MetricProps = {
  title: string;
  value: string | number;
  note?: string;
  statusText?: string;
  statusTone?: "green" | "amber";
};

export function Metric({ title, value, note, statusText, statusTone = "green" }: MetricProps) {
  return (
    <Card className="metric">
      <div className="metric-head">
        <Typography.Text type="secondary">{title}</Typography.Text>
        {statusText ? <span className={`metric-pill ${statusTone}`}>{statusText}</span> : null}
      </div>
      <div className="metric-value">{value}</div>
      {note ? <div className="metric-note">{note}</div> : null}
    </Card>
  );
}
