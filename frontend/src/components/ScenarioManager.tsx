import { Box, Button, Card, Dialog, PopupLayout, Typography } from "./ui";
import { t } from "../locale";
import { useState } from "react";
import type { ScenarioWorkspace } from "../types";

type Props = {
  scenarios: ScenarioWorkspace[];
  currentId?: string;
  onRename: (scenario: ScenarioWorkspace, name: string) => Promise<void>;
  onDelete: (scenario: ScenarioWorkspace) => Promise<void>;
  onClose: () => void;
};

export function ScenarioManager(props: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [deleting, setDeleting] = useState<string>();

  async function perform(action: () => Promise<void>, message: string) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
      setDeleting(undefined);
      setNotice(message);
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message
          : "Não foi possível atualizar a ocorrência",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog onDismiss={busy ? undefined : props.onClose} aria-label={t("Manage scenarios")}>
      <PopupLayout title={t("Manage scenarios")} eyebrow={t("Your workspaces")} size="wide" onClose={props.onClose} closeDisabled={busy}
        feedback={<>
          {error && <p className="manager-error" role="alert">{error}</p>}
          {notice && <p className="manager-notice" role="status">{notice}</p>}
        </>}>
        <Typography as="p" variant="body">
          {t(
            "Rename a scenario or remove it and its results from your workspace.",
          )}
        </Typography>
        <Box className="scenario-list">
          {props.scenarios.map((scenario) => (
            <ScenarioRow
              key={`${scenario.id}/${scenario.revision}`}
              scenario={scenario}
              current={scenario.id === props.currentId}
              busy={busy}
              deleting={deleting === scenario.id}
              onRename={(name) =>
                void perform(
                  () => props.onRename(scenario, name),
                  "Nome da ocorrência guardado.",
                )
              }
              onConfirm={() =>
                void perform(
                  () => props.onDelete(scenario),
                  `“${scenario.name}” eliminada.`,
                )
              }
              onDelete={() => {
                setDeleting(scenario.id);
                setError("");
                setNotice("");
              }}
              onCancel={() => setDeleting(undefined)}
            />
          ))}
          {!props.scenarios.length && (
            <Typography as="p" variant="body">
              {t("No scenarios left. Close this window to create a new one.")}
            </Typography>
          )}
        </Box>
      </PopupLayout>
    </Dialog>
  );
}

function ScenarioRow(props: {
  scenario: ScenarioWorkspace;
  current: boolean;
  busy: boolean;
  deleting: boolean;
  onRename: (name: string) => void;
  onDelete: () => void;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(props.scenario.name);
  const trimmed = name.trim();
  return (
    <Card density="compact" shadow="none" className="scenario-row">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (trimmed && trimmed !== props.scenario.name)
            props.onRename(trimmed);
        }}
      >
        <label>
          {t("Scenario name")}{" "}
          {props.current && (
            <span className="current-scenario">{t("Current")}</span>
          )}
          <input
            type="text"
            value={name}
            maxLength={120}
            required
            disabled={props.busy || props.deleting}
            onChange={(event) => setName(event.target.value)}
            aria-label={`Nome de ${props.scenario.name}`}
          />
        </label>
        <Box className="manager-actions">
          <Button
            variant="secondary"
            type="submit"
            disabled={
              props.busy ||
              props.deleting ||
              !trimmed ||
              trimmed === props.scenario.name
            }
          >
            {t("Save name")}
          </Button>
          <Button
            variant="outline"
            intent="danger"
            type="button"
            disabled={props.busy || props.deleting}
            onClick={props.onDelete}
          >
            {t("Delete")}
          </Button>
        </Box>
      </form>
      {props.deleting && (
        <Card density="compact" shadow="none" className="delete-confirmation">
          <Typography as="p" variant="body">
            {t("Delete")} <strong>{props.scenario.name}</strong>
            {t(
              "? Its points, closures, and simulation results will no longer be available in the app. You cannot undo this here.",
            )}
          </Typography>
          <Box className="manager-actions">
            <Button
              variant="outline"
              intent="danger"
              disabled={props.busy}
              onClick={props.onConfirm}
            >
              {props.busy ? "A eliminar…" : "Eliminar ocorrência"}
            </Button>
            <Button
              variant="secondary"
              disabled={props.busy}
              onClick={props.onCancel}
            >
              {t("Keep scenario")}
            </Button>
          </Box>
        </Card>
      )}
    </Card>
  );
}
