import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ColumnDef, flexRender, getCoreRowModel, useReactTable } from "@tanstack/react-table";
import { ChevronRight, Filter } from "lucide-react";
import { Link } from "react-router-dom";
import { apiClient, ApiSession } from "../api/client";
import { LeadListItem } from "../lib/types";
import { formatDate, scoreBucket, scoreBucketTone, withinDateRange } from "../lib/utils";

interface LeadsPageProps {
  session: ApiSession;
}

export function LeadsPage({ session }: LeadsPageProps) {
  const [city, setCity] = useState("");
  const [niche, setNiche] = useState("");
  const [bucket, setBucket] = useState<"" | "high-fit" | "mid-fit" | "low-fit">("");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");

  const leadsQuery = useQuery({
    queryKey: ["leads"],
    queryFn: () => apiClient.listLeads(session, { page: 1, limit: 100 }),
  });

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
      const matchesDate = withinDateRange(item.created_at, fromDate, toDate);
      return matchesCity && matchesNiche && matchesBucket && matchesDate;
    });
  }, [bucket, city, fromDate, items, niche, toDate]);

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
        <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-5">
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
