import { Box, Button, Card } from "./ui";
import { t } from "../locale";
import { useEffect, useState } from "react";
import { useLoading } from "../loading";

export type TimelineChangeSource = "manual" | "playback";
type Props = {
  minute: number;
  duration: number;
  forecast: number;
  frameReady?: boolean;
  pauseSignal?: string;
  onMinute: (value: number, source: TimelineChangeSource) => void;
  onForecast: (value: number) => void;
};

export function Timeline({
  minute,
  duration,
  forecast,
  frameReady = true,
  pauseSignal,
  onMinute,
  onForecast,
}: Props) {
  const [playing, setPlaying] = useState(false);
  const { isLoading } = useLoading();
  useEffect(() => {
    if (isLoading) setPlaying(false);
  }, [isLoading]);
  useEffect(() => {
    if (pauseSignal) setPlaying(false);
  }, [pauseSignal]);
  useEffect(() => {
    if (!playing || !frameReady) return;
    const timer = window.setInterval(
      () => onMinute(minute >= duration ? 0 : minute + 1, "playback"),
      350,
    );
    return () => clearInterval(timer);
  }, [playing, frameReady, minute, duration, onMinute]);
  return (
    <Card
      density="compact"
      shadow="none"
      className="timeline panel"
      aria-label={t("Simulation timeline")}
    >
      <Button
        variant="secondary"
        className="play"
        aria-label={playing ? "Pausar reprodução" : "Reproduzir simulação"}
        onClick={() => setPlaying(!playing)}
      >
        {playing ? "Ⅱ" : "▶"}
      </Button>
      <Box className="time">
        <span>{t("SIM TIME")}</span>
        <Box>
          <strong>{minute}</strong>
          <em>min</em>
        </Box>
      </Box>
      <Box className="timeline-track">
        <input
          aria-label={t("Simulation time")}
          type="range"
          min="0"
          max={duration}
          value={minute}
          onChange={(event) => onMinute(Number(event.target.value), "manual")}
        />
        <Box className="timeline-scale" aria-hidden="true">
          <span>00</span>
          <span>{Math.round(duration / 2)}</span>
          <span>{duration}</span>
        </Box>
      </Box>
      <Box className="forecast-options" role="group" aria-label={t("Forecast window")}>
        <span className="forecast-label">{t("Forecast window")}</span>
        {[10, 30, 60].map((value) => (
          <Button
            variant="secondary"
            type="button"
            key={value}
            className={forecast === value ? "active" : ""}
            aria-pressed={forecast === value}
            onClick={() => onForecast(value)}
          >
            +{value}
          </Button>
        ))}
      </Box>
      <span className="horizon">
        <b>{t("HORIZON")}</b>
        {duration} min
      </span>
    </Card>
  );
}
