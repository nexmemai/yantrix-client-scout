import { FormEvent, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ColumnDef, flexRender, getCoreRowModel, useReactTable } from "@tanstack/react-table";
import { ChevronRight, Filter, Play } from "lucide-react";
import { Link } from "react-router-dom";
import { apiClient, ApiSession } from "../api/client";
import { LeadListItem } from "../lib/types";
import { formatDate, scoreBucket, scoreBucketTone, withinDateRange } from "../lib/utils";

interface LeadsPageProps {
  session: ApiSession;
}

export function LeadsPage({ session }: LeadsPageProps) {
  const queryClient = useQueryClient();
  const [city, setCity] = useState("");
  const [niche, setNiche] = useState("");
  const [bucket, setBucket] = useState<"" | "high-fit" | "mid-fit" | "low-fit">("");
  const [agencyBucket, setAgencyBucket] = useState("");
  const [leadStatus, setLeadStatus] = useState("");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [runNiche, setRunNiche] = useState("dental");
  const [runCity, setRunCity] = useState("");
  const [maxBusinesses, setMaxBusinesses] = useState(25);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);

  const leadsQuery = useQuery({
    queryKey: ["leads"],
    queryFn: () => apiClient.listLeads(session, { page: 1, limit: 100 }),
  });

  const runScoutMutation = useMutation({
    mutationFn: () =>
      apiClient.runScout(session, {
        niche: runNiche.trim(),
        city: runCity.trim(),
        max_businesses: maxBusinesses,
      }),
    onSuccess: (response) => {
      setActiveJobId(response.job_id);
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });

  const jobStatusQuery = useQuery({
    queryKey: ["jobs", activeJobId],
    queryFn: () => apiClient.getJob(session, activeJobId as string),
    enabled: Boolean(activeJobId),
    refetchInterval: (query) => {
      const data = query.state.data;
      return data?.status === "completed" || data?.status === "failed" ? false : 4000;
    },
  });

  useEffect(() => {
    const status = jobStatusQuery.data?.status;
    if (status === "completed") {
      queryClient.invalidateQueries({ queryKey: ["leads"] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    }
  }, [jobStatusQuery.data?.status, queryClient]);

  const items = leadsQuery.data?.items ?? [];
  const niches = useMemo(
    () => Array.from(new Set(items.map((item) => item.category).filter(Boolean))).sort(),
    [items],
  );

  const filtered = useMemo(() => {
    return items.filter((item) => {
      const itemBucket = scoreBucket(item.overall_score);
      const matchesCity = city ? (item.city ?? "").toLowerCase().includes(city.toLowerCase()) : true;
      const matchesNiche = niche ? (item.category ?? "") === niche : true;
      const matchesBucket = bucket ? itemBucket === bucket : true;
      const matchesAgency = agencyBucket ? item.agency_fit_bucket === agencyBucket : true;
      const matchesStatus = leadStatus ? item.lead_status === leadStatus : true;
      const matchesDate = withinDateRange(item.created_at, fromDate, toDate);
      return matchesCity && matchesNiche && matchesBucket && matchesAgency && matchesStatus && matchesDate;
    });
  }, [agencyBucket, bucket, city, fromDate, items, leadStatus, niche, toDate]);

  const columns = useMemo<ColumnDef<LeadListItem>[]>(
    () => [
      {
        header: "Lead",
        accessorKey: "name",
        cell: ({ row }) => (
          <Link className="table-row-link flex items-center justify-between gap-3 rounded-md px-2 py-1 -mx-2" to={`/leads/${row.original.id}`}>
            <div>
              <div className="font-semibold">{row.original.name}</div>
              <div className="text-xs text-[var(--muted)]">{row.original.category ?? "Unknown niche"}</div>
            </div>
            <ChevronRight className="h-4 w-4 text-[var(--muted)]" />
          </Link>
        ),
      },
      {
        header: "City",
        accessorKey: "city",
      },
      {
        header: "Website",
        cell: ({ row }) => (row.original.has_website ? "Yes" : "No"),
      },
      {
        header: "Status",
        cell: ({ row }) => (
          <span className="rounded-full border border-[var(--line)] bg-white/70 px-2 py-1 text-xs font-semibold">
            {row.original.lead_status}
          </span>
        ),
      },
      {
        header: "Score",
        cell: ({ row }) => {
          const currentBucket = scoreBucket(row.original.overall_score);
          return (
            <div className="flex items-center gap-2">
              <span className="font-semibold">{row.original.overall_score ?? 0}</span>
              <span className={`rounded-full px-2 py-1 text-xs font-semibold ${scoreBucketTone(currentBucket)}`}>
                {currentBucket}
              </span>
            </div>
          );
        },
      },
      {
        header: "Agency fit",
        cell: ({ row }) => (
          <div className="grid gap-1 text-sm">
            <span className="font-semibold">{row.original.agency_fit_bucket ?? "-"}</span>
            <span className="text-xs text-[var(--muted)]">
              {row.original.estimated_deal_value ? `₹${row.original.estimated_deal_value.toLocaleString("en-IN")}` : "-"}
            </span>
          </div>
        ),
      },
      {
        header: "Created",
        cell: ({ row }) => formatDate(row.original.created_at),
      },
    ],
    [],
  );

  const table = useReactTable({
    data: filtered,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  const job = jobStatusQuery.data;
  const jobRunning = runScoutMutation.isPending || job?.status === "running" || job?.status === "pending";
  const jobProgressText = job
    ? `${job.total_scored || job.total_audited || job.total_discovered} / ${Math.max(job.total_discovered, maxBusinesses)} leads processed`
    : "No active scout job";

  const submitRunScout = (event: FormEvent) => {
    event.preventDefault();
    if (!runNiche.trim() || !runCity.trim() || jobRunning) {
      return;
    }
    runScoutMutation.mutate();
  };

  return (
    <div className="grid gap-4">
      <section className="surface section-band">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-2xl font-extrabold">Leads</div>
            <div className="mt-1 text-sm text-[var(--muted)]">
              Filter live scout output by location, niche, fit, and freshness.
            </div>
          </div>
          <div className="inline-flex items-center gap-2 rounded-full border border-[var(--line)] bg-white/70 px-3 py-2 text-xs font-semibold text-[var(--muted)]">
            <Filter className="h-3.5 w-3.5 text-[var(--warm)]" />
            {filtered.length} visible
          </div>
        </div>
        <form className="mt-5 grid gap-3 border-y border-[var(--line)] py-4 lg:grid-cols-[1fr_1fr_160px_auto]" onSubmit={submitRunScout}>
          <input
            className="field"
            placeholder="Niche"
            value={runNiche}
            onChange={(event) => setRunNiche(event.target.value)}
          />
          <input
            className="field"
            placeholder="City"
            value={runCity}
            onChange={(event) => setRunCity(event.target.value)}
          />
          <input
            className="field"
            max={100}
            min={1}
            type="number"
            value={maxBusinesses}
            onChange={(event) => setMaxBusinesses(Number(event.target.value))}
          />
          <button
            className="button button-primary h-11 px-4 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-60"
            disabled={jobRunning || !runNiche.trim() || !runCity.trim()}
            type="submit"
          >
            <Play className="h-4 w-4" />
            {jobRunning ? "Running..." : "Run Scout"}
          </button>
          <div className="lg:col-span-4">
            {job ? (
              <div className="inline-flex max-w-full flex-wrap items-center gap-2 rounded-full border border-[var(--line)] bg-white/70 px-3 py-2 text-xs font-semibold text-[var(--muted)]">
                <span className={job.status === "failed" ? "text-[var(--danger)]" : "text-[var(--accent)]"}>
                  Job {job.status}
                </span>
                <span>{job.niche ?? runNiche} in {job.city ?? runCity}</span>
                <span>{jobProgressText}</span>
              </div>
            ) : null}
            {runScoutMutation.isError ? (
              <div className="mt-2 text-sm text-[var(--danger)]">{(runScoutMutation.error as Error).message}</div>
            ) : null}
            {jobStatusQuery.isError ? (
              <div className="mt-2 text-sm text-[var(--danger)]">{(jobStatusQuery.error as Error).message}</div>
            ) : null}
          </div>
        </form>
        <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-7">
          <input className="field" placeholder="City" value={city} onChange={(event) => setCity(event.target.value)} />
          <select className="field" value={niche} onChange={(event) => setNiche(event.target.value)}>
            <option value="">All niches</option>
            {niches.map((item) => (
              <option key={item} value={item ?? ""}>
                {item}
              </option>
            ))}
          </select>
          <select className="field" value={bucket} onChange={(event) => setBucket(event.target.value as typeof bucket)}>
            <option value="">All score buckets</option>
            <option value="high-fit">high-fit</option>
            <option value="mid-fit">mid-fit</option>
            <option value="low-fit">low-fit</option>
          </select>
          <select className="field" value={agencyBucket} onChange={(event) => setAgencyBucket(event.target.value)}>
            <option value="">All agency fits</option>
            <option value="hot">hot</option>
            <option value="warm">warm</option>
            <option value="cold">cold</option>
            <option value="skip">skip</option>
          </select>
          <select className="field" value={leadStatus} onChange={(event) => setLeadStatus(event.target.value)}>
            <option value="">All statuses</option>
            <option value="new">new</option>
            <option value="contacted">contacted</option>
            <option value="replied">replied</option>
            <option value="meeting_set">meeting_set</option>
            <option value="proposal_sent">proposal_sent</option>
            <option value="won">won</option>
            <option value="lost">lost</option>
            <option value="ignored">ignored</option>
          </select>
          <input className="field" type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} />
          <input className="field" type="date" value={toDate} onChange={(event) => setToDate(event.target.value)} />
        </div>
      </section>

      <section className="surface-strong table-wrap">
        {leadsQuery.isLoading ? (
          <div className="p-6 text-sm text-[var(--muted)]">Loading leads…</div>
        ) : leadsQuery.isError ? (
          <div className="p-6 text-sm text-[var(--danger)]">{(leadsQuery.error as Error).message}</div>
        ) : (
          <table>
            <thead>
              {table.getHeaderGroups().map((headerGroup) => (
                <tr key={headerGroup.id}>
                  {headerGroup.headers.map((header) => (
                    <th key={header.id}>
                      {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                    </th>
                  ))}
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.map((row) => (
                <tr key={row.id}>
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
