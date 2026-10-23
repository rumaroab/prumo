import { useAppLocation } from "../navigation";
import { Box, ButtonLink, Card, SectionContainer, Typography } from "./ui";
import { statusLabel, t } from "../locale";
import { useEffect, useState } from "react";
import { api } from "../api";
import type { Run, ScenarioWorkspace } from "../types";

type ArchiveSection = { title: string; records: unknown[] };

export function PlanningArchive({ scenarioId }: { scenarioId: string }) {
  useAppLocation();
  const selectedRunId = new URLSearchParams(window.location.search).get("run");
  const [scenario, setScenario] = useState<ScenarioWorkspace>();
  const [sections, setSections] = useState<ArchiveSection[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    const sources: [string, Promise<unknown>][] = [
      [
        "Saved situation",
        api.exerciseSituation(scenarioId).then((value) => [value]),
      ],
      ["Situation snapshots", api.snapshots(scenarioId)],
      ["Missions", api.missions(scenarioId)],
      ["Response plans", api.responsePlans(scenarioId)],
      ["Response experiments", api.responseExperiments(scenarioId)],
      ["Rehearsals", api.exerciseRuns(scenarioId)],
      ["Fire results", api.scenarioRuns(scenarioId)],
    ];
    void api
      .scenario(scenarioId)
      .then((value) => {
        if (!active) return;
        setScenario(value);
        setSections([
          { title: "Saved planning closures", records: value.closures },
          {
            title: "Saved containment tasks",
            records: value.containment_tasks,
          },
          { title: "Saved allocation plans", records: value.allocation_plans },
          { title: "Saved response teams", records: value.teams },
          { title: "Saved points", records: value.points },
        ]);
      })
      .catch((reason) => {
        if (active)
          setError(
            reason instanceof Error ? reason.message : t("Archive unavailable"),
          );
      });
    void Promise.allSettled(sources.map(([, result]) => result)).then(
      (results) => {
        if (!active) return;
        setSections((current) => [
          ...current,
          ...results.map((result, index) => ({
            title: sources[index][0],
            records:
              result.status === "fulfilled" && Array.isArray(result.value)
                ? result.value
                : [],
          })),
        ]);
      },
    );
    return () => {
      active = false;
    };
  }, [scenarioId]);
  return (
    <SectionContainer
      as="main"
      containerClassName="ds-stack"
      className="management-shell archive-page"
    >
      <header className="management-header">
        <Box>
          <Typography as="span" variant="label" className="eyebrow">
            {t("Read-only archive")}
          </Typography>
          <Typography as="h1" variant="h1">
            Arquivo de planos
          </Typography>
          <Typography as="p" variant="body">
            {t(
              "Saved planning inputs and results are retained for reference. Current journeys and reports belong in Mobility.",
            )}
          </Typography>
        </Box>
        <ButtonLink
          variant="primary"
          href={`/scenarios/${scenarioId}/mobility`}
        >
          {t("Open mobility")}
        </ButtonLink>
      </header>
      {error && (
        <Typography
          role="alert"
          as="p"
          variant="small"
          className="management-error"
        >
          {error}
        </Typography>
      )}
      {sections.map((section) => (
        <Card
          as="section"
          density="default"
          shadow="card"
          className="management-panel"
          key={section.title}
        >
          <Typography as="h2" variant="h3">
            {t(section.title)} · {section.records.length}
          </Typography>
          {section.records.length ? (
            section.records.map((raw, index) => {
              const record = raw as Record<string, unknown>;
              const run =
                section.title === "Fire results" ? (raw as Run) : undefined;
              return (
                <Card
                  as="details"
                  density="compact"
                  shadow="none"
                  key={String(record.id || index)}
                  className="archive-record"
                  open={Boolean(
                    record.id &&
                      (window.location.pathname.endsWith(String(record.id)) ||
                        selectedRunId === record.id),
                  )}
                >
                  <summary>
                    {String(
                      record.name ||
                        record.title ||
                        record.id ||
                        `${t("Record")} ${index + 1}`,
                    )}
                    {record.status
                      ? ` · ${statusLabel(String(record.status))}`
                      : ""}
                  </summary>
                  {run && ["ready", "partial"].includes(run.status) && (
                    <a
                      href={
                        run.mode === "allocation_comparison"
                          ? `/api/runs/${run.id}/allocation-comparison`
                          : `/scenarios/${scenarioId}/simulation?run=${run.id}`
                      }
                    >
                      {t("Open saved result")}
                    </a>
                  )}
                  <pre>{JSON.stringify(raw, null, 2)}</pre>
                </Card>
              );
            })
          ) : (
            <Typography as="p" variant="small" className="empty-note">
              {t("No saved records.")}
            </Typography>
          )}
        </Card>
      ))}
    </SectionContainer>
  );
}
