import { useEffect, useState } from "react";
import { apiErrorMessage } from "../locale";
import type { AreaPreparation } from "../types";
import { Typography } from "./ui";

export function PreparationFeedback({
  job,
  imported = false,
}: {
  job: AreaPreparation;
  imported?: boolean;
}) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!job.retry_at || job.status !== "running") return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [job.retry_at, job.status]);
  const seconds = job.retry_at
    ? Math.max(0, Math.ceil((Date.parse(job.retry_at) - now) / 1000))
    : 0;
  const upstreamFailure =
    job.failure_code?.startsWith("overpass_") ||
    /Overpass/i.test(job.error || "");
  const source = job.source_progress;
  const region = source?.region === "portugal" ? "Portugal" : source?.region === "spain" ? "Espanha" : "";
  const localSources = Object.values(job.datasets).flatMap((dataset) =>
    dataset.osm_provenance?.provider === "local" && dataset.osm_provenance.data_timestamp
      ? [dataset.osm_provenance]
      : [],
  );
  const dataDates = [...new Set(localSources.map((value) => value.data_timestamp!))];
  const stale = localSources.some((value) => value.stale);
  const refreshFailed = localSources.some((value) => value.refresh_error);
  const downloaded = source?.downloaded_bytes;
  const total = source?.total_bytes;
  const megabytes = (bytes: number) => Math.round(bytes / 1024 ** 2).toLocaleString("pt-PT");
  return (
    <>
      {source?.provider === "local" && job.status === "running" && (
        <Typography as="p" variant="body" role="status">
          {source.phase === "waiting" && "A aguardar a preparação dos mapas locais."}
          {source.phase === "downloading" && `A descarregar os mapas de ${region}. Este ficheiro será reutilizado nas próximas preparações.`}
          {source.phase === "validating" && `A verificar os mapas locais${region ? ` de ${region}` : ""}.`}
          {source.phase === "extracting" && "A ler os mapas locais para a área selecionada."}
          {source.phase === "ready" && "Mapas locais disponíveis."}
          {source.phase === "downloading" && downloaded != null && (
            <> {megabytes(downloaded)} MB{total != null ? ` de ${megabytes(total)} MB` : ""}.</>
          )}
        </Typography>
      )}
      {source?.phase === "fallback" && job.status === "running" && (
        <>
          <Typography as="p" variant="body" role="status">
            Não foi possível usar os mapas locais para esta área. A tentar o serviço de mapas em linha, mantendo a cobertura selecionada.
          </Typography>
          {source.reason && <details>
            <summary>Detalhes técnicos da alternativa em linha</summary>
            <Typography as="p" variant="body">{source.reason}</Typography>
          </details>}
        </>
      )}
      {dataDates.map((stamp) => (
        <Typography key={stamp} as="p" variant="body">
          Mapas locais: dados de {new Date(stamp).toLocaleDateString("pt-PT", { timeZone: "UTC" })}.
        </Typography>
      ))}
      {(stale || refreshFailed) && <Typography as="p" variant="body" role="status">
        {refreshFailed
          ? "A atualização dos mapas falhou. Está a ser usada a última cópia válida, com a data indicada acima."
          : "Os mapas locais têm mais de sete dias. A preparação mantém a cópia válida enquanto é procurada uma atualização."}
      </Typography>}
      {job.tile_progress && source?.provider !== "local" && (
        <Typography as="p" variant="body" role="status">
          Partes descarregadas: {job.tile_progress.completed} de{" "}
          {job.tile_progress.total}.
        </Typography>
      )}
      {job.status === "running" && job.retry_at && (
        <Typography as="p" variant="body" role="status">
          Serviço de mapas ocupado. Nova tentativa em {seconds} s.
        </Typography>
      )}
      {job.error && (
        <>
          <Typography as="p" variant="body" role="alert">
            {upstreamFailure && job.retryable !== false
              ? job.failure_code
                ? "O serviço de mapas está temporariamente indisponível. O trabalho concluído foi guardado; tente novamente para continuar."
                : "O serviço de mapas está temporariamente indisponível. Tente novamente para continuar com os dados disponíveis."
              : apiErrorMessage(job.error, 500)}
          </Typography>
          {upstreamFailure && imported && (
            <Typography as="p" variant="body">
              A ocorrência continua guardada. A área selecionada mantém-se
              igual.
            </Typography>
          )}
          <details>
            <summary>Detalhes técnicos originais</summary>
            <Typography as="p" variant="body">
              {job.error}
            </Typography>
            {source?.phase === "fallback" && source.reason && (
              <Typography as="p" variant="body">Mapas locais: {source.reason}</Typography>
            )}
          </details>
        </>
      )}
    </>
  );
}
