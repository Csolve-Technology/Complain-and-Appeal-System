"use client";

import { useChiroAuth } from "@/components/ChiroAuthProvider";
import { getCachedAccessToken } from "@/services/auth-session";
import { authFetch } from "@/services/auth-http";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Breadcrumb from "@/components/Breadcrumbs/Breadcrumb";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { RefreshCcw, Download } from "lucide-react";

/* ===================== Types ===================== */

type SummaryResp = {
  total_cases: number;
  open_cases: number;
  resolved_cases: number;
  avg_resolution_days: number | null;
};

type StatusRow   = { status: string; count: number };
type OfficeRow   = { office_id: number | string; office_name: string; count: number };
type CategoryRow = { category: string; count: number };
type AssigneeRow = { user_id: number | string; full_name: string; active_cases: number };

type Filters = {
  date_from?: string;
  date_to?: string;
  status?: string;
  category?: string;
  office_id?: string;
};

/* ===================== Config ===================== */

const API_URL = process.env.NEXT_PUBLIC_API_URL;
const USE_MOCK = process.env.NEXT_PUBLIC_USE_MOCK === "1";

const allowedRoles = new Set(["Director", "President Office", "President"]);

/* ===================== Utilities ===================== */

const fetchAllPaginated = async <T,>(url: string, headers: HeadersInit): Promise<T[]> => {
  let next: string | null = url;
  const all: T[] = [];
  while (next) {
    const res: Response = await authFetch(next, { headers, cache: "no-store" });
    if (!res.ok) throw new Error(`${res.status} while loading ${next}`);
    const data = await res.json();
    if (Array.isArray(data)) {
      all.push(...(data as T[]));
      next = null;
    } else if (Array.isArray((data as any)?.results)) {
      all.push(...((data as any).results as T[]));
      next = (data as any).next || null;
    } else {
      all.push(data as T);
      next = null;
    }
  }
  return all;
};

const qs = (o: Record<string, any>) =>
  Object.entries(o)
    .filter(([_, v]) => v !== undefined && v !== "" && v !== null)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join("&");

/* Tiny bar visual using Tailwind (no chart lib) */
const Bar = ({ value, max, label }: { value: number; max: number; label?: string }) => {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-full rounded bg-gray-200 dark:bg-dark-3">
        <div
          className="h-2 rounded bg-[#5750f1]"
          style={{ width: `${pct}%` }}
          aria-label={label}
        />
      </div>
      <span className="min-w-12 text-right text-xs text-gray-600 dark:text-dark-6">{pct}%</span>
    </div>
  );
};

/* ===================== Mock Data ===================== */

const mockOffices = [
  { id: "1", name: "President Office" },
  { id: "2", name: "Regional Admin Office" },
  { id: "3", name: "Kebele 01" },
  { id: "4", name: "Kebele 02" },
  { id: "5", name: "Civil Service Bureau" },
];

const mockCategories = ["service", "land", "employment", "finance", "security"];

const mockSummary: SummaryResp = {
  total_cases: 1248,
  open_cases: 812,                // open = not in {resolved, rejected, closed}
  resolved_cases: 436,            // resolved+closed
  avg_resolution_days: 6.2,
};

const mockByStatus: StatusRow[] = [
  { status: "pending",            count: 420 },
  { status: "in investigation",   count: 392 },
  { status: "resolved",           count: 280 },
  { status: "rejected",           count: 78 },
  { status: "closed",             count: 78 },
];

const mockByOffice: OfficeRow[] = [
  { office_id: "1", office_name: "President Office",       count: 106 },
  { office_id: "2", office_name: "Regional Admin Office",  count: 235 },
  { office_id: "3", office_name: "Kebele 01",              count: 318 },
  { office_id: "4", office_name: "Kebele 02",              count: 287 },
  { office_id: "5", office_name: "Civil Service Bureau",   count: 302 },
];

const mockByCategory: CategoryRow[] = [
  { category: "service",    count: 410 },
  { category: "land",       count: 295 },
  { category: "employment", count: 238 },
  { category: "finance",    count: 175 },
  { category: "security",   count: 130 },
];

const mockTopAssignees: AssigneeRow[] = [
  { user_id: "11", full_name: "Abel Mohammed",    active_cases: 36 },
  { user_id: "12", full_name: "Samiya Ali",       active_cases: 33 },
  { user_id: "13", full_name: "Daniel Tesfaye",   active_cases: 29 },
  { user_id: "14", full_name: "Mekdes Girma",     active_cases: 24 },
  { user_id: "15", full_name: "Biniam Hailu",     active_cases: 22 },
];

/* Filters applied to mocks to feel “real” */
function filterMocks(
  search: string,
  filters: Filters,
) {
  const q = search.trim().toLowerCase();

  // status
  let s = [...mockByStatus];
  if (filters.status && filters.status !== "all") {
    s = s.filter(r => r.status.toLowerCase() === filters.status?.toLowerCase());
  }
  if (q) {
    s = s.filter(r => r.status.toLowerCase().includes(q));
  }

  // office
  let o = [...mockByOffice];
  if (filters.office_id && filters.office_id !== "all") {
    o = o.filter(r => String(r.office_id) === String(filters.office_id));
  }
  if (q) {
    o = o.filter(r => r.office_name.toLowerCase().includes(q));
  }

  // category
  let c = [...mockByCategory];
  if (filters.category && filters.category !== "all") {
    c = c.filter(r => r.category.toLowerCase() === filters.category?.toLowerCase());
  }
  if (q) {
    c = c.filter(r => r.category.toLowerCase().includes(q));
  }

  // assignees
  let a = [...mockTopAssignees];
  if (q) {
    a = a.filter(r => r.full_name.toLowerCase().includes(q));
  }

  // summary stays same (could compute from filtered sets if desired)
  return { summary: mockSummary, byStatus: s, byOffice: o, byCategory: c, topAssignees: a };
}

/* ===================== Page ===================== */

export default function ReportsPage() {
  const { can } = useChiroAuth();
  const router = useRouter();

  const token =
    typeof window !== "undefined" ? getCachedAccessToken() : null;
  const role =
    typeof window !== "undefined" ? localStorage.getItem("role") : null;

  const headers: HeadersInit = useMemo(() => (token ? { Authorization: `Bearer ${token}` } : {}) as HeadersInit, [token]);

  // Guard
  useEffect(() => {
    if (!can("cas_app.view_case")) {
      router.replace("/dashboard");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [role]);

  // Filters
  const [filters, setFilters] = useState<Filters>({
    date_from: "",
    date_to: "",
    status: "all",
    category: "all",
    office_id: "all",
  });

  // Data
  const [summary, setSummary] = useState<SummaryResp | null>(null);
  const [byStatus, setByStatus] = useState<StatusRow[]>([]);
  const [byOffice, setByOffice] = useState<OfficeRow[]>([]);
  const [byCategory, setByCategory] = useState<CategoryRow[]>([]);
  const [topAssignees, setTopAssignees] = useState<AssigneeRow[]>([]);

  // Options
  const [offices, setOffices] = useState<Array<{ id: string; name: string }>>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [statuses] = useState<string[]>([
    "pending",
    "in investigation",
    "resolved",
    "rejected",
    "closed",
  ]);

  // UX
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");

  /* ---------- Load Options ---------- */
  const loadOptions = async () => {
    // Mock options
    if (USE_MOCK || !API_URL || !token) {
      setOffices(mockOffices.map(o => ({ id: o.id, name: o.name })));
      setCategories([...mockCategories]);
      return;
    }

    try {
      const [off, cats] = await Promise.all([
        fetchAllPaginated<{ id: string | number; name: string }>(`${API_URL}/offices/`, headers),
        fetchAllPaginated<{ name: string }>(`${API_URL}/categories/`, headers).catch(() => []),
      ]);
      setOffices(off.map(o => ({ id: String(o.id), name: o.name })));
      setCategories((cats as any[]).map((c: any) => c.name).filter(Boolean));
    } catch {
      // non-fatal fallback to mock
      setOffices(mockOffices.map(o => ({ id: o.id, name: o.name })));
      setCategories([...mockCategories]);
    }
  };

  /* ---------- Load Reports ---------- */
  const loadReports = async () => {
    // Mocked
    if (USE_MOCK || !API_URL || !token) {
      const m = filterMocks(search, filters);
      setSummary(m.summary);
      setByStatus(m.byStatus);
      setByOffice(m.byOffice);
      setByCategory(m.byCategory);
      setTopAssignees(m.topAssignees);
      return;
    }

    setLoading(true);
    setError("");
    try {
      const q = qs({
        date_from: filters.date_from || undefined,
        date_to: filters.date_to || undefined,
        status: filters.status !== "all" ? filters.status : undefined,
        category: filters.category !== "all" ? filters.category : undefined,
        office_id: filters.office_id !== "all" ? filters.office_id : undefined,
        search: search || undefined,
      });

      const [s, bs, bo, bc, ta] = await Promise.all([
        authFetch(`${API_URL}/reports/summary/${q ? `?${q}` : ""}`, { headers, cache: "no-store" }).then((r: Response) => r.json()) as Promise<SummaryResp>,
        authFetch(`${API_URL}/reports/cases_by_status/${q ? `?${q}` : ""}`, { headers, cache: "no-store" }).then((r: Response) => r.json()) as Promise<StatusRow[]>,
        authFetch(`${API_URL}/reports/cases_by_office/${q ? `?${q}` : ""}`, { headers, cache: "no-store" }).then((r: Response) => r.json()) as Promise<OfficeRow[]>,
        authFetch(`${API_URL}/reports/cases_by_category/${q ? `?${q}` : ""}`, { headers, cache: "no-store" }).then((r: Response) => r.json()) as Promise<CategoryRow[]>,
        authFetch(`${API_URL}/reports/top_assignees/${q ? `?${q}` : ""}`, { headers, cache: "no-store" }).then((r: Response) => r.json()) as Promise<AssigneeRow[]>,
      ]);

      setSummary(s);
      setByStatus(Array.isArray(bs) ? bs : []);
      setByOffice(Array.isArray(bo) ? bo : []);
      setByCategory(Array.isArray(bc) ? bc : []);
      setTopAssignees(Array.isArray(ta) ? ta : []);
    } catch (e: any) {
      setError(e?.message || "Failed to load reports");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadOptions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    loadReports();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters.date_from, filters.date_to, filters.status, filters.category, filters.office_id, search]);

  /* ---------- Derived ---------- */
  const maxStatus   = useMemo(() => Math.max(0, ...byStatus.map((r) => r.count)), [byStatus]);
  const maxOffice   = useMemo(() => Math.max(0, ...byOffice.map((r) => r.count)), [byOffice]);
  const maxCategory = useMemo(() => Math.max(0, ...byCategory.map((r) => r.count)), [byCategory]);
  const maxAssignee = useMemo(() => Math.max(0, ...topAssignees.map((r) => r.active_cases)), [topAssignees]);

  /* ---------- Export CSV helpers ---------- */
  const exportCsv = (rows: any[], columns: string[], filename: string) => {
    const csv = [
      columns.join(","),
      ...rows.map((r) =>
        columns
          .map((c) => {
            const v = r[c] ?? "";
            const s = String(v).replace(/"/g, '""');
            return `"${s}"`;
          })
          .join(","),
      ),
    ].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.setAttribute("download", filename);
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  return (
    <>
      <Breadcrumb pageName="Reports" />

      <div className={cn("rounded-[10px] bg-white p-5 shadow-1 dark:bg-gray-dark dark:shadow-card")}>
        {/* Filters */}
        <div className="mb-6 grid grid-cols-1 gap-3 md:grid-cols-12">
          <div className="md:col-span-3">
            <label className="mb-1 block text-sm font-medium">From</label>
            <Input
              type="date"
              value={filters.date_from}
              onChange={(e) => setFilters((s) => ({ ...s, date_from: e.target.value }))}
            />
          </div>
          <div className="md:col-span-3">
            <label className="mb-1 block text-sm font-medium">To</label>
            <Input
              type="date"
              value={filters.date_to}
              onChange={(e) => setFilters((s) => ({ ...s, date_to: e.target.value }))}
            />
          </div>
          <div className="md:col-span-2">
            <label className="mb-1 block text-sm font-medium">Status</label>
            <Select
              value={filters.status}
              onValueChange={(v) => setFilters((s) => ({ ...s, status: v }))}
            >
              <SelectTrigger>
                <SelectValue placeholder="Status" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All</SelectItem>
                {statuses.map((s) => (
                  <SelectItem key={s} value={s}>
                    {s[0].toUpperCase() + s.slice(1)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="md:col-span-2">
            <label className="mb-1 block text-sm font-medium">Category</label>
            <Select
              value={filters.category}
              onValueChange={(v) => setFilters((s) => ({ ...s, category: v }))}
            >
              <SelectTrigger>
                <SelectValue placeholder="Category" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All</SelectItem>
                {categories.map((c) => (
                  <SelectItem key={c} value={c}>
                    {c[0].toUpperCase() + c.slice(1)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="md:col-span-2">
            <label className="mb-1 block text-sm font-medium">Office</label>
            <Select
              value={filters.office_id}
              onValueChange={(v) => setFilters((s) => ({ ...s, office_id: v }))}
            >
              <SelectTrigger>
                <SelectValue placeholder="Office" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All</SelectItem>
                {offices.map((o) => (
                  <SelectItem key={o.id} value={o.id}>
                    {o.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Search & Actions */}
          <div className="md:col-span-12 mt-2 flex flex-wrap items-center gap-2">
            <Input
              placeholder="Search (status, office, category, assignee)…"
              className="w-full max-w-xs"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <Button variant="ghost" onClick={loadReports} title="Refresh">
              <RefreshCcw className="h-4 w-4" />
            </Button>
            <Button
              className="bg-[#5750f1] text-white hover:opacity-90"
              onClick={() => {
                const flat = [
                  { metric: "total_cases", value: summary?.total_cases ?? 0 },
                  { metric: "open_cases", value: summary?.open_cases ?? 0 },
                  { metric: "resolved_cases", value: summary?.resolved_cases ?? 0 },
                  { metric: "avg_resolution_days", value: summary?.avg_resolution_days ?? "" },
                ];
                exportCsv(flat, ["metric", "value"], "summary.csv");
              }}
            >
              <Download className="mr-2 h-4 w-4" />
              Export Summary CSV
            </Button>
          </div>
        </div>

        {/* Error / Loading */}
        {loading && <div className="py-6 text-center text-gray-500 dark:text-gray-300">Loading…</div>}
        {!!error && !loading && (
          <div className="py-6 text-center text-red-500">{error}</div>
        )}

        {/* KPIs */}
        {!loading && !error && (
          <>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
              <div className="rounded-xl border p-4 dark:border-dark-3">
                <div className="text-sm text-gray-500 dark:text-dark-6">Total Cases</div>
                <div className="mt-1 text-2xl font-bold text-[#5750f1]">
                  {summary?.total_cases ?? "—"}
                </div>
              </div>
              <div className="rounded-xl border p-4 dark:border-dark-3">
                <div className="text-sm text-gray-500 dark:text-dark-6">Open Cases</div>
                <div className="mt-1 text-2xl font-bold">{summary?.open_cases ?? "—"}</div>
              </div>
              <div className="rounded-xl border p-4 dark:border-dark-3">
                <div className="text-sm text-gray-500 dark:text-dark-6">Resolved Cases</div>
                <div className="mt-1 text-2xl font-bold">{summary?.resolved_cases ?? "—"}</div>
              </div>
              <div className="rounded-xl border p-4 dark:border-dark-3">
                <div className="text-sm text-gray-500 dark:text-dark-6">Avg Resolution (days)</div>
                <div className="mt-1 text-2xl font-bold">
                  {summary?.avg_resolution_days ?? "—"}
                </div>
              </div>
            </div>

            {/* Status Breakdown */}
            <div className="mt-6 rounded-xl border p-4 dark:border-dark-3">
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-lg font-semibold">By Status</h3>
                <Button
                  variant="outline"
                  onClick={() => exportCsv(byStatus, ["status", "count"], "by_status.csv")}
                >
                  <Download className="mr-2 h-4 w-4" />
                  Export
                </Button>
              </div>
              <Table>
                <TableHeader>
                  <TableRow className="[&>th]:text-left">
                    <TableHead>Status</TableHead>
                    <TableHead>Count</TableHead>
                    <TableHead>Share</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {byStatus.map((r) => (
                    <TableRow key={r.status}>
                      <TableCell className="capitalize">{r.status}</TableCell>
                      <TableCell>{r.count}</TableCell>
                      <TableCell><Bar value={r.count} max={maxStatus} label={r.status} /></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>

            {/* Office Breakdown */}
            <div className="mt-6 rounded-xl border p-4 dark:border-dark-3">
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-lg font-semibold">By Office</h3>
                <Button
                  variant="outline"
                  onClick={() => exportCsv(byOffice, ["office_name", "count"], "by_office.csv")}
                >
                  <Download className="mr-2 h-4 w-4" />
                  Export
                </Button>
              </div>
              <Table>
                <TableHeader>
                  <TableRow className="[&>th]:text-left">
                    <TableHead>Office</TableHead>
                    <TableHead>Count</TableHead>
                    <TableHead>Share</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {byOffice.map((r) => (
                    <TableRow key={String(r.office_id)}>
                      <TableCell>{r.office_name}</TableCell>
                      <TableCell>{r.count}</TableCell>
                      <TableCell><Bar value={r.count} max={maxOffice} label={r.office_name} /></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>

            {/* Category Breakdown */}
            <div className="mt-6 rounded-xl border p-4 dark:border-dark-3">
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-lg font-semibold">By Category</h3>
                <Button
                  variant="outline"
                  onClick={() => exportCsv(byCategory, ["category", "count"], "by_category.csv")}
                >
                  <Download className="mr-2 h-4 w-4" />
                  Export
                </Button>
              </div>
              <Table>
                <TableHeader>
                  <TableRow className="[&>th]:text-left">
                    <TableHead>Category</TableHead>
                    <TableHead>Count</TableHead>
                    <TableHead>Share</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {byCategory.map((r) => (
                    <TableRow key={r.category}>
                      <TableCell className="capitalize">{r.category}</TableCell>
                      <TableCell>{r.count}</TableCell>
                      <TableCell><Bar value={r.count} max={maxCategory} label={r.category} /></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>

            {/* Top Assignees */}
            <div className="mt-6 rounded-xl border p-4 dark:border-dark-3">
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-lg font-semibold">Top Assignees (Active Cases)</h3>
                <Button
                  variant="outline"
                  onClick={() => exportCsv(topAssignees, ["full_name", "active_cases"], "top_assignees.csv")}
                >
                  <Download className="mr-2 h-4 w-4" />
                  Export
                </Button>
              </div>
              <Table>
                <TableHeader>
                  <TableRow className="[&>th]:text-left">
                    <TableHead>Assignee</TableHead>
                    <TableHead>Active Cases</TableHead>
                    <TableHead>Share</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {topAssignees.map((r) => (
                    <TableRow key={String(r.user_id)}>
                      <TableCell>{r.full_name}</TableCell>
                      <TableCell>{r.active_cases}</TableCell>
                      <TableCell><Bar value={r.active_cases} max={maxAssignee} label={r.full_name} /></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </>
        )}
      </div>
    </>
  );
}
