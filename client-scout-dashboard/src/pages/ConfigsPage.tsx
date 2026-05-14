import { FormEvent, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Save, Trash2 } from "lucide-react";
import { apiClient, ApiSession } from "../api/client";
import { ConfigWeights, NicheConfig } from "../lib/types";

interface ConfigsPageProps {
  session: ApiSession;
}

const emptyWeights: ConfigWeights = {
  weak_website: 20,
  lead_capture_gap: 25,
  outdated_contact: 10,
  high_ticket: 20,
  trust_gap: 10,
  automation_gap: 15,
};

export function ConfigsPage({ session }: ConfigsPageProps) {
  const queryClient = useQueryClient();
  const [activeNiche, setActiveNiche] = useState<string>("");
  const [draft, setDraft] = useState<NicheConfig | null>(null);

  const configsQuery = useQuery({
    queryKey: ["configs"],
    queryFn: () => apiClient.listConfigs(session),
  });

  const configs = configsQuery.data ?? [];
  const activeConfig = useMemo(
    () => configs.find((item) => item.niche === activeNiche) ?? null,
    [activeNiche, configs],
  );

  useEffect(() => {
    if (!activeNiche && configs.length) {
      setActiveNiche(configs[0].niche);
    }
  }, [activeNiche, configs]);

  useEffect(() => {
    if (activeConfig) {
      setDraft({ ...activeConfig, weights: { ...activeConfig.weights } });
    }
  }, [activeConfig]);

  const saveMutation = useMutation({
    mutationFn: async (payload: NicheConfig) =>
      apiClient.upsertConfig(session, payload.niche, {
        weights: payload.weights,
        prompt_template: payload.prompt_template ?? null,
      }),
    onSuccess: (saved) => {
      queryClient.invalidateQueries({ queryKey: ["configs"] });
      setActiveNiche(saved.niche);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (niche: string) => apiClient.deleteConfig(session, niche),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["configs"] });
      setActiveNiche("");
      setDraft(null);
    },
  });

  const startCreate = () => {
    setActiveNiche("__new__");
    setDraft({
      id: "new",
      niche: "",
      weights: { ...emptyWeights },
      prompt_template: "",
      is_default: false,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!draft) return;
    saveMutation.mutate(draft);
  };

  return (
    <div className="grid gap-4 xl:grid-cols-[320px_minmax(0,1fr)]">
      <section className="surface section-band">
        <div className="mb-4 flex items-center justify-between">
          <div className="text-lg font-extrabold">Niche configs</div>
          <button className="button button-primary h-10 px-3 text-sm font-semibold" onClick={startCreate}>
            <Plus className="h-4 w-4" />
            New
          </button>
        </div>
        <div className="grid gap-2">
          {configs.map((config) => (
            <button
              key={config.id}
              className={`button h-auto justify-start px-3 py-3 text-left ${
                activeNiche === config.niche ? "bg-[var(--accent)] text-white" : "button-secondary"
              }`}
              onClick={() => setActiveNiche(config.niche)}
            >
              <div>
                <div className="text-sm font-semibold">{config.niche}</div>
                <div className={`text-xs ${activeNiche === config.niche ? "text-white/80" : "text-[var(--muted)]"}`}>
                  {config.is_default ? "default preset" : "editable preset"}
                </div>
              </div>
            </button>
          ))}
        </div>
      </section>

      <section className="surface-strong p-5">
        {!draft ? (
          <div className="text-sm text-[var(--muted)]">Select a niche config to edit.</div>
        ) : (
          <form className="grid gap-5" onSubmit={submit}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-xl font-extrabold">{draft.id === "new" ? "Create niche config" : draft.niche}</div>
                <div className="mt-1 text-sm text-[var(--muted)]">Tune score weights and prompt guidance for this niche.</div>
              </div>
              <div className="flex gap-2">
                {!draft.is_default && draft.id !== "new" ? (
                  <button
                    className="button button-danger h-10 px-3 text-sm font-semibold"
                    onClick={() => deleteMutation.mutate(draft.niche)}
                    type="button"
                  >
                    <Trash2 className="h-4 w-4" />
                    Delete
                  </button>
                ) : null}
                <button className="button button-primary h-10 px-3 text-sm font-semibold" type="submit" disabled={saveMutation.isPending}>
                  <Save className="h-4 w-4" />
                  Save
                </button>
              </div>
            </div>

            <label className="block">
              <div className="mb-2 text-sm font-semibold">Niche key</div>
              <input
                className="field"
                disabled={draft.id !== "new"}
                value={draft.niche}
                onChange={(event) => setDraft({ ...draft, niche: event.target.value })}
              />
            </label>

            <div className="grid gap-4 md:grid-cols-2">
              {Object.entries(draft.weights).map(([key, value]) => (
                <label className="block" key={key}>
                  <div className="mb-2 text-sm font-semibold">{key}</div>
                  <input
                    className="field"
                    max={100}
                    min={0}
                    type="number"
                    value={value}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        weights: {
                          ...draft.weights,
                          [key]: Number(event.target.value),
                        },
                      })
                    }
                  />
                </label>
              ))}
            </div>

            <label className="block">
              <div className="mb-2 text-sm font-semibold">Prompt template</div>
              <textarea
                className="field min-h-40"
                value={draft.prompt_template ?? ""}
                onChange={(event) => setDraft({ ...draft, prompt_template: event.target.value })}
              />
            </label>

            {saveMutation.isError ? <div className="text-sm text-[var(--danger)]">{(saveMutation.error as Error).message}</div> : null}
          </form>
        )}
      </section>
    </div>
  );
}
