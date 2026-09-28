interface PanelTitleProps {
  title: string;
  subtitle: string;
}
export const PanelTitle = ({ title, subtitle }: PanelTitleProps) => (
  <div className="panel-title">
    <div>
      <small>EXECUTOR BALANCER</small>
      <h2>{title}</h2>
    </div>
    <span>{subtitle}</span>
  </div>
);
