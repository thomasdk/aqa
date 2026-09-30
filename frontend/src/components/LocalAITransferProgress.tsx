import { useTranslation } from "react-i18next";
import { formatNumber } from "../i18n";
import { Card, SectionHeader } from "./design-system";

export function formatBytes(bytes: number | null | undefined): string | null {
  if (!Number.isFinite(bytes) || !bytes || bytes < 0) return null;
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000;
    unit += 1;
  }
  const digits = value >= 10 || unit === 0 ? 0 : 2;
  return `${formatNumber(value, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })} ${units[unit]}`;
}

type LocalAITransferProgressProps = {
  id: string;
  title: string;
  description: string;
  loaded: number;
  total: number;
  ariaLabel: string;
};

export function LocalAITransferProgress({
  id,
  title,
  description,
  loaded,
  total,
  ariaLabel,
}: LocalAITransferProgressProps) {
  const { t } = useTranslation();
  const maximum = total > 0 ? total : Math.max(loaded, 0);
  const value = Math.min(Math.max(loaded, 0), maximum);
  const percent = total > 0 ? Math.round((value / total) * 100) : null;
  const progressText =
    percent === null ? t("localAi.progressPending") : t("localAi.progressPercent", { percent });

  return (
    <Card className="local-ai-transfer-progress-card" aria-labelledby={id}>
      <SectionHeader title={title} titleId={id} />
      <p>{description}</p>
      <div className="local-ai-transfer-track-row">
        <progress
          className="local-ai-progress"
          value={value}
          max={total || undefined}
          aria-label={ariaLabel}
          aria-valuetext={progressText}
        />
        {total > 0 && <span className="local-ai-model-transfer-total">{formatBytes(total)}</span>}
      </div>
      <div className="local-ai-progress-meta">
        <span>{progressText}</span>
        <span>{formatBytes(value) ?? "0 B"}</span>
      </div>
    </Card>
  );
}
