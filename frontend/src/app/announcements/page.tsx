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
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { AnimatedModal } from "@/components/ui/animated-modal";
import { SuccessModal } from "@/components/ui/success-modal";
import { Plus, Settings, RefreshCcw } from "lucide-react";

/* ===================== Types (aligned with your model) ===================== */

type ApiOffice = { id: number | string; name: string };
type ApiGroup  = { id: number | string; name: string };

type Announcement = {
  id: number | string;
  title: string;
  content: string;
  is_active?: boolean;
  created_at?: string | null;
  created_by?: any;

  // M2M can be ids or objects depending on serializer
  recipients_groups?: (number | string | ApiGroup)[] | null;
  recipients_offices?: (number | string | ApiOffice)[] | null;
};

type CreateForm = {
  title: string;
  content: string;                  // <- matches backend
  audienceType: "roles" | "offices";
  groupIds: (string | number)[];    // <- send group IDs
  officeIds: (string | number)[];   // <- send office IDs
};

type EditForm = {
  title: string;
  content: string;
  audienceType: "roles" | "offices";
  groupIds: (string | number)[];
  officeIds: (string | number)[];
};

/* ===================== Helpers ===================== */

const allowedToManage = new Set(["Director", "President Office", "President"]);

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

// Turn ids/strings/objects into display names using a map (id → name)
function toNames(
  items: Array<string | number | { id?: string|number; name?: string }> | undefined | null,
  map: Map<string, string>
): string[] {
  if (!Array.isArray(items)) return [];
  return items.map((it) => {
    if (typeof it === "object" && it !== null) {
      const name = (it as any).name ?? map.get(String((it as any).id));
      return name ?? String((it as any).id ?? "");
    }
    // string or number – try map; fallback to the raw value
    return map.get(String(it)) ?? String(it);
  });
}

/* ===================== Page ===================== */

export default function AnnouncementsPage() {
  const { can } = useChiroAuth();
  const router = useRouter();
  const API_URL = process.env.NEXT_PUBLIC_API_URL;
  const token = typeof window !== "undefined" ? getCachedAccessToken() : null;
  const role  = typeof window !== "undefined" ? localStorage.getItem("role")  : null;

  const canManage = can("cas_app.add_announcement") || can("cas_app.change_announcement") || can("cas_app.delete_announcement");
  const headers: HeadersInit = useMemo(() => (token ? { Authorization: `Bearer ${token}` } : {}) as HeadersInit, [token]);

  // Data
  const [rows, setRows] = useState<Announcement[]>([]);
  const [offices, setOffices] = useState<ApiOffice[]>([]);
  const [groups, setGroups] = useState<ApiGroup[]>([]); // roles/groups with id+name

  // Fast lookup maps (id → name)
  const groupMap  = useMemo(() => {
    const m = new Map<string, string>();
    groups.forEach(g => m.set(String(g.id), g.name));
    return m;
  }, [groups]);

  const officeMap = useMemo(() => {
    const m = new Map<string, string>();
    offices.forEach(o => m.set(String(o.id), o.name));
    return m;
  }, [offices]);

  // UX
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Filters
  const [search, setSearch] = useState("");

  // Create
  const [openCreate, setOpenCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");
  const [createForm, setCreateForm] = useState<CreateForm>({
    title: "",
    content: "",
    audienceType: "roles",
    groupIds: [],
    officeIds: [],
  });

  // Manage (edit/delete)
  const [openManage, setOpenManage] = useState(false);
  const [selected, setSelected] = useState<Announcement | null>(null);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [editError, setEditError] = useState("");
  const [editForm, setEditForm] = useState<EditForm>({
    title: "",
    content: "",
    audienceType: "roles",
    groupIds: [],
    officeIds: [],
  });

  // Success
  const [successOpen, setSuccessOpen] = useState(false);
  const [successMsg, setSuccessMsg] = useState("");

  /* ---------- Load ---------- */

  const loadAnnouncements = async () => {
    if (!API_URL || !token) return;
    try {
      setLoading(true);
      setError("");
      const list = await fetchAllPaginated<Announcement>(`${API_URL}/announcements/`, headers);
      list.sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")));
      setRows(list);
    } catch (e: any) {
      setError(e?.message || "Failed to load announcements");
    } finally {
      setLoading(false);
    }
  };

  const loadOptions = async () => {
    if (!API_URL || !token) return;
    try {
      const [off, gr] = await Promise.all([
        can("cas_app.view_office") ? fetchAllPaginated<ApiOffice>(`${API_URL}/offices/`, headers) : Promise.resolve([]),
        can("auth.view_group") ? fetchAllPaginated<ApiGroup>(`${API_URL}/groups/`, headers) : Promise.resolve([]),
      ]);
      setOffices(off);
      setGroups(gr);
    } catch {
      // non-fatal
    }
  };

  useEffect(() => {
    loadAnnouncements();
    loadOptions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ---------- Filter ---------- */

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return rows;
    return rows.filter((r) =>
      [r.title, r.content].filter(Boolean).some((v) => String(v).toLowerCase().includes(term)),
    );
  }, [rows, search]);

  /* ---------- Create ---------- */

  const resetCreate = () =>
    setCreateForm({ title: "", content: "", audienceType: "roles", groupIds: [], officeIds: [] });

  const submitCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!API_URL) return setCreateError("API URL not set");
    if (!token)   return setCreateError("You are not authenticated.");
    if (!canManage) return setCreateError("You do not have permission.");
    if (!createForm.title.trim())   return setCreateError("Title is required.");
    if (!createForm.content.trim()) return setCreateError("Content is required.");

    const usingRoles = createForm.audienceType === "roles";
    const recipients_groups  = usingRoles ? createForm.groupIds  : [];
    const recipients_offices = usingRoles ? []                   : createForm.officeIds;

    if (usingRoles && recipients_groups.length === 0)
      return setCreateError("Select at least one role.");
    if (!usingRoles && recipients_offices.length === 0)
      return setCreateError("Select at least one office.");

    const payload = {
      title: createForm.title.trim(),
      content: createForm.content.trim(), // REQUIRED by backend
      is_active: true,
      recipients_groups,
      recipients_offices,
    };

    try {
      setCreating(true);
      const res = await authFetch(`${API_URL}/announcements/`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...headers },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const msg = await res.text();
        throw new Error(msg || `Create failed: ${res.status}`);
      }
      setOpenCreate(false);
      resetCreate();
      await loadAnnouncements();
      setSuccessMsg("Announcement created successfully.");
      setSuccessOpen(true);
      setTimeout(() => setSuccessOpen(false), 3000);
    } catch (e: any) {
      setCreateError(e?.message || "Failed to create announcement");
    } finally {
      setCreating(false);
    }
  };

  /* ---------- Manage (Edit/Delete) ---------- */

  const openManageModal = (row: Announcement) => {
    setSelected(row);
    // Pre-fill edit form with IDs
    const groupsFromRow = (row.recipients_groups || []).map((g) =>
      typeof g === "object" ? (g as ApiGroup).id : g,
    );
    const officesFromRow = (row.recipients_offices || []).map((o) =>
      typeof o === "object" ? (o as ApiOffice).id : o,
    );
    const audienceType: "roles" | "offices" =
      groupsFromRow.length > 0 ? "roles" : "offices";

    setEditForm({
      title: row.title || "",
      content: row.content || "",
      audienceType,
      groupIds: groupsFromRow as (string | number)[],
      officeIds: officesFromRow as (string | number)[],
    });

    setEditError("");
    setSaving(false);
    setDeleting(false);
    setOpenManage(true);
  };

  const submitSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!API_URL || !selected) return;
    if (!token) return setEditError("You are not authenticated.");
    if (!canManage) return setEditError("You do not have permission.");
    if (!editForm.title.trim())   return setEditError("Title is required.");
    if (!editForm.content.trim()) return setEditError("Content is required.");

    const usingRoles = editForm.audienceType === "roles";
    const payload = {
      title: editForm.title.trim(),
      content: editForm.content.trim(),
      recipients_groups:  usingRoles ? editForm.groupIds  : [],
      recipients_offices: usingRoles ? []                  : editForm.officeIds,
    };

    try {
      setSaving(true);
      const res = await authFetch(`${API_URL}/announcements/${selected.id}/`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...headers },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const msg = await res.text();
        throw new Error(msg || `Update failed: ${res.status}`);
      }
      setOpenManage(false);
      await loadAnnouncements();
      setSuccessMsg("Announcement updated successfully.");
      setSuccessOpen(true);
      setTimeout(() => setSuccessOpen(false), 3000);
    } catch (e: any) {
      setEditError(e?.message || "Failed to update announcement");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!API_URL || !selected) return;
    if (!token) return setEditError("You are not authenticated.");
    if (!canManage) return setEditError("You do not have permission.");
    try {
      setDeleting(true);
      const res = await authFetch(`${API_URL}/announcements/${selected.id}/`, {
        method: "DELETE",
        headers,
      });
      if (!res.ok && res.status !== 204) {
        const msg = await res.text();
        throw new Error(msg || `Delete failed: ${res.status}`);
      }
      setOpenManage(false);
      await loadAnnouncements();
      setSuccessMsg("Announcement deleted successfully.");
      setSuccessOpen(true);
      setTimeout(() => setSuccessOpen(false), 3000);
    } catch (e: any) {
      setEditError(e?.message || "Failed to delete announcement");
    } finally {
      setDeleting(false);
    }
  };

  /* ---------- Render ---------- */

  return (
    <>
      <Breadcrumb pageName="Announcements" />

      <div className={cn("rounded-[10px] bg-white p-5 shadow-1 dark:bg-gray-dark dark:shadow-card")}>
        {/* Top bar */}
        <div className="mb-4 flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <Input
              placeholder="Search title or content…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-[300px]"
            />
            <Button variant="ghost" onClick={loadAnnouncements} title="Refresh">
              <RefreshCcw className="h-4 w-4" />
            </Button>
          </div>

          {canManage && (
            <Button
              className="bg-blue-600 text-white hover:bg-blue-700"
              onClick={() => {
                setCreateError("");
                resetCreate();
                setOpenCreate(true);
              }}
            >
              <Plus className="mr-2 h-4 w-4" />
              Add New
            </Button>
          )}
        </div>

        {/* Table */}
        <Table>
          <TableHeader>
            <TableRow className="[&>th]:text-center">
              <TableHead className="!text-left">Title</TableHead>
              <TableHead>Audience</TableHead>
              <TableHead>Date</TableHead>
              {canManage && <TableHead>Action</TableHead>}
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && (
              <TableRow>
                <TableCell colSpan={canManage ? 4 : 3} className="py-4 text-center text-gray-500 dark:text-gray-300">
                  Loading…
                </TableCell>
              </TableRow>
            )}

            {!loading && !!error && (
              <TableRow>
                <TableCell colSpan={canManage ? 4 : 3} className="py-4 text-center text-red-500">
                  {error}
                </TableCell>
              </TableRow>
            )}

            {!loading && !error && filtered.length === 0 && (
              <TableRow>
                <TableCell colSpan={canManage ? 4 : 3} className="py-4 text-center text-gray-500 dark:text-gray-300">
                  No announcements found
                </TableCell>
              </TableRow>
            )}

            {!loading && !error && filtered.map((a) => {
              // Convert whatever the API returned (ids/objects/strings) to *names*
              const roleNames   = toNames(a.recipients_groups   as any, groupMap);
              const officeNames = toNames(a.recipients_offices  as any, officeMap);

              const audienceStr =
                roleNames.length   > 0 ? `Roles: ${roleNames.join(", ")}`
              : officeNames.length > 0 ? `Offices: ${officeNames.join(", ")}`
              : "—";

              return (
                <TableRow key={String(a.id)} className="text-center text-base font-medium text-dark dark:text-white">
                  <TableCell className="!text-left">
                    <div className="font-semibold text-[#5750f1]">{a.title}</div>
                    {a.content && (
                      <div className="text-sm text-gray-600 dark:text-dark-6 line-clamp-2">
                        {a.content}
                      </div>
                    )}
                  </TableCell>
                  <TableCell className="text-sm">{audienceStr}</TableCell>
                  <TableCell className="text-sm">{a.created_at ? String(a.created_at).slice(0, 10) : "—"}</TableCell>
                  {canManage && (
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="mx-auto flex items-center gap-2"
                        onClick={() => openManageModal(a)}
                        title="Manage"
                      >
                        <Settings className="h-4 w-4 text-blue-600" />
                        Manage
                      </Button>
                    </TableCell>
                  )}
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      {/* Create Modal */}
      <AnimatedModal
        open={openCreate}
        onClose={() => setOpenCreate(false)}
        title="Create Announcement"
        maxWidthClassName="max-w-xl"
      >
        {!canManage ? (
          <div className="text-sm text-gray-500">You do not have permission.</div>
        ) : (
          <form className="space-y-4" onSubmit={submitCreate}>
            <Input
              placeholder="Title *"
              value={createForm.title}
              onChange={(e) => setCreateForm((s) => ({ ...s, title: e.target.value }))}
              required
            />
            <textarea
              className="w-full rounded border border-gray-300 p-2 dark:border-dark-3 dark:bg-dark-2"
              rows={5}
              placeholder="Content *"
              value={createForm.content}
              onChange={(e) => setCreateForm((s) => ({ ...s, content: e.target.value }))}
              required
            />

            {/* Audience selector */}
            <div className="flex gap-3">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="audienceType"
                  checked={createForm.audienceType === "roles"}
                  onChange={() => setCreateForm((s) => ({ ...s, audienceType: "roles", officeIds: [] }))}
                />
                Roles
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="audienceType"
                  checked={createForm.audienceType === "offices"}
                  onChange={() => setCreateForm((s) => ({ ...s, audienceType: "offices", groupIds: [] }))}
                />
                Offices
              </label>
            </div>

            {createForm.audienceType === "roles" ? (
              <div>
                <div className="mb-1 text-sm font-medium">Select Roles</div>
                <div className="max-h-40 overflow-auto rounded border p-2 dark:border-dark-3">
                  {groups.length === 0 ? (
                    <div className="text-sm text-gray-500">No roles found.</div>
                  ) : (
                    groups.map((g) => (
                      <label key={String(g.id)} className="flex items-center gap-2 py-1 text-sm">
                        <input
                          type="checkbox"
                          checked={createForm.groupIds.map(String).includes(String(g.id))}
                          onChange={(e) => {
                            const checked = e.target.checked;
                            setCreateForm((s) => ({
                              ...s,
                              groupIds: checked
                                ? [...s.groupIds, g.id]
                                : s.groupIds.filter((x) => String(x) !== String(g.id)),
                            }));
                          }}
                        />
                        {g.name}
                      </label>
                    ))
                  )}
                </div>
              </div>
            ) : (
              <div>
                <div className="mb-1 text-sm font-medium">Select Offices</div>
                <div className="max-h-40 overflow-auto rounded border p-2 dark:border-dark-3">
                  {offices.length === 0 ? (
                    <div className="text-sm text-gray-500">No offices found.</div>
                  ) : (
                    offices.map((o) => (
                      <label key={String(o.id)} className="flex items-center gap-2 py-1 text-sm">
                        <input
                          type="checkbox"
                          checked={createForm.officeIds.map(String).includes(String(o.id))}
                          onChange={(e) => {
                            const checked = e.target.checked;
                            setCreateForm((s) => ({
                              ...s,
                              officeIds: checked
                                ? [...s.officeIds, o.id]
                                : s.officeIds.filter((x) => String(x) !== String(o.id)),
                            }));
                          }}
                        />
                        {o.name}
                      </label>
                    ))
                  )}
                </div>
              </div>
            )}

            {createError && <div className="text-sm text-red-500">{createError}</div>}

            <Button
              type="submit"
              className="w-full bg-blue-600 text-white hover:bg-blue-700"
              disabled={creating}
            >
              {creating ? "Creating..." : "Create"}
            </Button>
          </form>
        )}
      </AnimatedModal>

      {/* Manage Modal */}
      <AnimatedModal
        open={openManage}
        onClose={() => setOpenManage(false)}
        title={selected ? `Manage: ${selected.title}` : "Manage Announcement"}
        maxWidthClassName="max-w-xl"
      >
        {!canManage ? (
          <div className="text-sm text-gray-500">You do not have permission.</div>
        ) : !selected ? (
          <div className="text-sm text-gray-500">No announcement selected.</div>
        ) : (
          <form className="space-y-4" onSubmit={submitSave}>
            <Input
              placeholder="Title *"
              value={editForm.title}
              onChange={(e) => setEditForm((s) => ({ ...s, title: e.target.value }))}
              required
            />
            <textarea
              className="w-full rounded border border-gray-300 p-2 dark:border-dark-3 dark:bg-dark-2"
              rows={5}
              placeholder="Content *"
              value={editForm.content}
              onChange={(e) => setEditForm((s) => ({ ...s, content: e.target.value }))}
              required
            />

            {/* Audience toggle */}
            <div className="flex gap-3">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="editAudienceType"
                  checked={editForm.audienceType === "roles"}
                  onChange={() => setEditForm((s) => ({ ...s, audienceType: "roles", officeIds: [] }))}
                />
                Roles
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="editAudienceType"
                  checked={editForm.audienceType === "offices"}
                  onChange={() => setEditForm((s) => ({ ...s, audienceType: "offices", groupIds: [] }))}
                />
                Offices
              </label>
            </div>

            {/* Show the current audience as names (readable) */}
            <div className="rounded border p-3 text-xs dark:border-dark-3">
              <div className="font-medium mb-1">Current Audience</div>
              <div className="space-y-1">
                {editForm.audienceType === "roles" ? (
                  <div>
                    Roles:&nbsp;
                    {toNames(
                      (selected.recipients_groups || []).map((g) =>
                        typeof g === "object" ? (g as ApiGroup).id : g
                      ),
                      groupMap
                    ).join(", ") || "—"}
                  </div>
                ) : (
                  <div>
                    Offices:&nbsp;
                    {toNames(
                      (selected.recipients_offices || []).map((o) =>
                        typeof o === "object" ? (o as ApiOffice).id : o
                      ),
                      officeMap
                    ).join(", ") || "—"}
                  </div>
                )}
              </div>
            </div>

            {/* Editable audience pickers */}
            {editForm.audienceType === "roles" ? (
              <div>
                <div className="mb-1 text-sm font-medium">Select Roles</div>
                <div className="max-h-40 overflow-auto rounded border p-2 dark:border-dark-3">
                  {groups.length === 0 ? (
                    <div className="text-sm text-gray-500">No roles found.</div>
                  ) : (
                    groups.map((g) => (
                      <label key={String(g.id)} className="flex items-center gap-2 py-1 text-sm">
                        <input
                          type="checkbox"
                          checked={editForm.groupIds.map(String).includes(String(g.id))}
                          onChange={(e) => {
                            const checked = e.target.checked;
                            setEditForm((s) => ({
                              ...s,
                              groupIds: checked
                                ? [...s.groupIds, g.id]
                                : s.groupIds.filter((x) => String(x) !== String(g.id)),
                            }));
                          }}
                        />
                        {g.name}
                      </label>
                    ))
                  )}
                </div>
              </div>
            ) : (
              <div>
                <div className="mb-1 text-sm font-medium">Select Offices</div>
                <div className="max-h-40 overflow-auto rounded border p-2 dark:border-dark-3">
                  {offices.length === 0 ? (
                    <div className="text-sm text-gray-500">No offices found.</div>
                  ) : (
                    offices.map((o) => (
                      <label key={String(o.id)} className="flex items-center gap-2 py-1 text-sm">
                        <input
                          type="checkbox"
                          checked={editForm.officeIds.map(String).includes(String(o.id))}
                          onChange={(e) => {
                            const checked = e.target.checked;
                            setEditForm((s) => ({
                              ...s,
                              officeIds: checked
                                ? [...s.officeIds, o.id]
                                : s.officeIds.filter((x) => String(x) !== String(o.id)),
                            }));
                          }}
                        />
                        {o.name}
                      </label>
                    ))
                  )}
                </div>
              </div>
            )}

            {editError && <div className="text-sm text-red-500">{editError}</div>}

            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex gap-2">
                <Button
                  type="submit"
                  className="bg-blue-600 text-white hover:bg-blue-700"
                  disabled={saving}
                >
                  {saving ? "Saving..." : "Save Changes"}
                </Button>

                <Button
                  type="button"
                  className="bg-red-600 text-white hover:bg-red-700"
                  onClick={handleDelete}
                  disabled={deleting}
                >
                  {deleting ? "Deleting..." : "Delete"}
                </Button>
              </div>

              <div className="text-xs text-gray-500 dark:text-dark-6">
                Created: {selected?.created_at ? String(selected.created_at).slice(0, 10) : "—"}
              </div>
            </div>
          </form>
        )}
      </AnimatedModal>

      {/* Success modal */}
      <SuccessModal
        open={successOpen}
        onClose={() => setSuccessOpen(false)}
        title="Success"
        message={successMsg}
        autoCloseMs={3000}
      />
    </>
  );
}
