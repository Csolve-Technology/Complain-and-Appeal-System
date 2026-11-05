"use client";
import { useChiroAuth } from "@/components/ChiroAuthProvider";
import { getCachedAccessToken } from "@/services/auth-session";
import { authFetch } from "@/services/auth-http";
import { useEffect, useMemo, useState } from "react";
import Breadcrumb from "@/components/Breadcrumbs/Breadcrumb";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Plus, Settings } from "lucide-react";
import { AnimatedModal } from "@/components/ui/animated-modal";
import { SuccessModal } from "@/components/ui/success-modal";

/* ---------------- Types ---------------- */

type ApiGroup = {
  id: number | string;
  name: string;
  is_active?: boolean;
  created_at?: string;
  users_count?: number | null; // backend may send null
  permissions?: number[]; // permission IDs
  permission_codenames?: string[];
  permission_details?: Array<{
    id: number;
    codename: string;
    name: string;
    content_type__app_label: string;
    content_type__model: string;
  }>;
};

type Row = {
  id: number | string;
  name: string;
  is_active: boolean;
  created_at: string;
  users_count: number | null; // we'll compute if null
};

type ApiUser = {
  id: number | string;
  groups?: Array<{ name: string } | string> | null;
};

type Permission = {
  id: number;
  codename: string;
  name: string;
  content_type__app_label: string;
  content_type__model: string;
};

/* ---------------- Mapping helpers ---------------- */

const mapRow = (g: ApiGroup): Row => ({
  id: g.id,
  name: g.name,
  is_active: g.is_active ?? true,
  created_at: g.created_at ? String(g.created_at).slice(0, 10) : "—",
  users_count: typeof g.users_count === "number" ? g.users_count : null,
});

/* ---------------- Page ---------------- */

export default function RolesPage() {
  const { can } = useChiroAuth();
  const [syncMessage, setSyncMessage] = useState("");
  const API_URL = process.env.NEXT_PUBLIC_API_URL;
  const token =
    typeof window !== "undefined" ? getCachedAccessToken() : null;

  // Check if user is Admin
  const isAdmin = can("auth.view_group");
  const checkingAdmin = false;

  // table + search
  const [groups, setGroups] = useState<Row[]>([]);
  const [search, setSearch] = useState("");

  // UX
  const [loading, setLoading] = useState(false);
  const [pageError, setPageError] = useState("");

  // create modal
  const [openCreate, setOpenCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");
  const [createForm, setCreateForm] = useState<{ name: string }>({ name: "" });

  // details/edit/delete
  const [openDetails, setOpenDetails] = useState(false);
  const [detailsError, setDetailsError] = useState("");
  const [selected, setSelected] = useState<Row | null>(null);
  const [editing, setEditing] = useState(false);
  const [editForm, setEditForm] = useState<{ name: string }>({ name: "" });
  const [deleting, setDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  // success modal
  const [successOpen, setSuccessOpen] = useState(false);
  const [successMsg, setSuccessMsg] = useState("");

  // permissions
  const [allPermissions, setAllPermissions] = useState<Permission[]>([]);
  const [loadingPermissions, setLoadingPermissions] = useState(false);
  const [selectedPermissions, setSelectedPermissions] = useState<number[]>([]);

  /* ---------- Generic pagination-aware fetchers ---------- */

  const authHeaders: HeadersInit = token ? { Authorization: `Bearer ${token}` } : {};

  const fetchAllPaginated = async <T,>(startUrl: string): Promise<T[]> => {
    let all: T[] = [];
    let nextUrl: string | null = startUrl;

    while (nextUrl) {
      const res: Response = await authFetch(nextUrl, { headers: authHeaders, cache: "no-store" });
      if (!res.ok) throw new Error(`Failed to load: ${res.status}`);
      const data: any = await res.json();

      if (Array.isArray(data)) {
        all = all.concat(data);
        nextUrl = null;
      } else if (Array.isArray(data?.results)) {
        all = all.concat(data.results);
        nextUrl = data.next || null;
      } else {
        // unknown shape – try to coerce a single object
        all = all.concat(data);
        nextUrl = null;
      }
    }

    return all;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  };

  const fetchAllGroups = async (): Promise<ApiGroup[]> => {
    return fetchAllPaginated<ApiGroup>(`${API_URL}/groups/`);
  };

  const fetchAllUsers = async (): Promise<ApiUser[]> => {
    return fetchAllPaginated<ApiUser>(`${API_URL}/users/`);
  };

  const loadAllPermissions = async () => {
    if (!API_URL || !token) return;
    try {
      setLoadingPermissions(true);
      const res: Response = await authFetch(`${API_URL}/groups/all-permissions/`, {
        headers: authHeaders,
        cache: "no-store",
      });
      if (res.ok) {
        const data: Permission[] = await res.json();
        setAllPermissions(data || []);
      }
    } catch (err) {
      console.error("Failed to load permissions:", err);
    } finally {
      setLoadingPermissions(false);
    }
  };

  /* ---------- Load groups and fix user counts if missing ---------- */

  const loadGroups = async () => {
    if (!API_URL) {
      setPageError("ENV NEXT_PUBLIC_API_URL is not set");
      return;
    }
    try {
      setLoading(true);
      setPageError("");

      const apiGroups = await fetchAllGroups();
      let rows = (Array.isArray(apiGroups) ? apiGroups : []).map(mapRow);

      // For any roles with null users_count, try /groups/:id/users/ then fallback to aggregate over all users
      const missing = rows.filter((g) => g.users_count == null).map((g) => g.id);
      if (missing.length) {
        // 1) Attempt per-group users endpoint
        const tryPerGroupCounts = async () => {
          let updated: Record<string | number, number | null> = {};
          for (const gid of missing) {
            try {
              const res = await authFetch(`${API_URL}/groups/${gid}/users/`, {
                headers: authHeaders,
                cache: "no-store",
              });
              if (!res.ok) {
                updated[gid] = null; // mark as still missing
                continue;
              }
              const arr = await res.json();
              updated[gid] = Array.isArray(arr) ? arr.length : null;
            } catch {
              updated[gid] = null;
            }
          }
          return updated;
        };

        const perGroup = await tryPerGroupCounts();

        // See which are still missing
        const stillMissing = missing.filter((gid) => perGroup[gid] == null);

        // 2) Fallback: fetch all users and aggregate by group name
        let aggregated: Record<string, number> = {};
        if (stillMissing.length) {
          try {
            const users = await fetchAllUsers();
            const counts: Record<string, number> = {};
            for (const u of users) {
              const names =
                (u.groups || [])
                  .map((g) => (typeof g === "string" ? g : g?.name))
                  .filter(Boolean) as string[];
              names.forEach((name) => {
                counts[name] = (counts[name] || 0) + 1;
              });
            }
            aggregated = counts;
          } catch {
            // ignore – leave as empty
          }
        }

        // merge counts back into rows
        rows = rows.map((r) => {
          if (r.users_count != null) return r;
          // prefer per-group count if available, else aggregate by role name
          const fromPerGroup = perGroup[r.id];
          if (typeof fromPerGroup === "number") {
            return { ...r, users_count: fromPerGroup };
          }
          const fromAggregate = aggregated[r.name];
          return { ...r, users_count: typeof fromAggregate === "number" ? fromAggregate : 0 };
        });
      }

      setGroups(rows);
    } catch (err: any) {
      setPageError(err?.message || "Failed to load roles");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadGroups();
    loadAllPermissions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ---------- Filter ---------- */

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return groups;
    return groups.filter((g) => g.name.toLowerCase().includes(term));
  }, [groups, search]);

  /* ---------- Create ---------- */

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreateError("");
    if (!API_URL) return setCreateError("API URL not set");
    if (!token) return setCreateError("You are not authenticated");
    if (!createForm.name.trim()) return setCreateError("Role name is required");

    try {
      setCreating(true);
      
      // Create role
      const res = await authFetch(`${API_URL}/groups/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...authHeaders,
        },
        body: JSON.stringify({
          name: createForm.name.trim(),
          is_active: true,
        }),
      });
      if (!res.ok) {
        const msg = await res.text();
        throw new Error(msg || `Create failed: ${res.status}`);
      }
      
      const newGroup = await res.json();
      
      // Set permissions if any selected
      if (selectedPermissions.length > 0) {
        const permRes = await authFetch(`${API_URL}/groups/${newGroup.id}/set_permissions/`, {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
            ...authHeaders,
          },
          body: JSON.stringify({
            permission_ids: selectedPermissions,
          }),
        });
        if (!permRes.ok) {
          console.warn("Failed to set permissions, but role was created");
        }
      }
      
      await loadGroups();
      setOpenCreate(false);
      setCreateForm({ name: "" });
      setSelectedPermissions([]);

      setSuccessMsg("Role created successfully.");
      setSuccessOpen(true);
      setTimeout(() => setSuccessOpen(false), 3000);
    } catch (err: any) {
      setCreateError(err?.message || "Failed to create role");
    } finally {
      setCreating(false);
    }
  };

  /* ---------- Details / Edit / Delete ---------- */

  const openDetailsModal = async (row: Row) => {
    setSelected(row);
    setEditForm({ name: row.name });
    setDetailsError("");
    setConfirmDelete(false);
    
    // Load permissions for this role
    if (API_URL && token) {
      try {
        const res = await authFetch(`${API_URL}/groups/${row.id}/permissions/`, {
          headers: authHeaders,
          cache: "no-store",
        });
        if (res.ok) {
          const perms = await res.json();
          setSelectedPermissions(perms.map((p: any) => p.id));
        }
      } catch (err) {
        console.error("Failed to load role permissions:", err);
        setSelectedPermissions([]);
      }
    }
    
    setOpenDetails(true);
  };

  const handleUpdate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selected) return;
    setDetailsError("");
    if (!API_URL) return setDetailsError("API URL not set");
    if (!token) return setDetailsError("You are not authenticated");
    if (!editForm.name.trim()) return setDetailsError("Role name is required");

    try {
      can("auth.change_group") && setEditing(true);
      
      // Update role name
      const res = await authFetch(`${API_URL}/groups/${selected.id}/`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          ...authHeaders,
        },
        body: JSON.stringify({
          name: editForm.name.trim(),
        }),
      });
      if (!res.ok) {
        const msg = await res.text();
        throw new Error(msg || `Update failed: ${res.status}`);
      }
      
      // Update permissions
      const permRes = await authFetch(`${API_URL}/groups/${selected.id}/set_permissions/`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          ...authHeaders,
        },
        body: JSON.stringify({
          permission_ids: selectedPermissions,
        }),
      });
      if (!permRes.ok) {
        const msg = await permRes.text();
        throw new Error(msg || `Failed to update permissions: ${permRes.status}`);
      }
      
      await loadGroups();
      setOpenDetails(false);

      setSuccessMsg("Role updated successfully.");
      setSuccessOpen(true);
      setTimeout(() => setSuccessOpen(false), 3000);
    } catch (err: any) {
      setDetailsError(err?.message || "Failed to update role");
    } finally {
      setEditing(false);
    }
  };

  const handleDelete = async () => {
    if (!selected) return;
    setDetailsError("");
    if (!API_URL) return setDetailsError("API URL not set");
    if (!token) return setDetailsError("You are not authenticated");

    try {
      setDeleting(true);
      const res = await authFetch(`${API_URL}/groups/${selected.id}/`, {
        method: "DELETE",
        headers: { ...authHeaders },
      });
      if (!res.ok && res.status !== 204) {
        const msg = await res.text();
        throw new Error(msg || `Delete failed: ${res.status}`);
      }
      await loadGroups();
      setOpenDetails(false);

      setSuccessMsg("Role deleted successfully.");
      setSuccessOpen(true);
      setTimeout(() => setSuccessOpen(false), 3000);
    } catch (err: any) {
      setDetailsError(err?.message || "Failed to delete role");
    } finally {
      setDeleting(false);
    }
  };

  /* ---------- Render ---------- */

  // Redirect non-admin users
  useEffect(() => {
    if (!checkingAdmin && !isAdmin) {
      window.location.href = "/dashboard";
    }
  }, [checkingAdmin, isAdmin]);

  if (checkingAdmin) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-sm text-gray-500">Loading...</div>
      </div>
    );
  }

  if (!isAdmin) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-red-600 mb-2">Access Denied</h1>
          <p className="text-gray-600">You do not have permission to access this page.</p>
        </div>
      </div>
    );
  }

  return (
    <>
      <Breadcrumb pageName="Roles" />
      {can("auth.add_group") && <div className="my-4 space-y-2"><button type="button" className="rounded bg-primary px-4 py-2 text-white" onClick={async () => {
        try {
          const response = await authFetch(`${API_URL}/groups/sync-roles/`, { method: "POST" });
          const data = await response.json();
          if (!response.ok) throw new Error(data.detail || "Unable to synchronize roles.");
          setSyncMessage("Roles imported. Reload this page to see them; new roles have no permissions until you grant them.");
        } catch (error) { setSyncMessage(error instanceof Error ? error.message : "Unable to synchronize roles."); }
      }}>Load Chiro Auth roles</button>{syncMessage && <p role="status">{syncMessage}</p>}</div>}


      <div
        className={cn(
          "rounded-[10px] bg-white p-5 shadow-1 dark:bg-gray-dark dark:shadow-card",
        )}
      >
        {/* Top bar */}
        <div className="mb-4 flex flex-wrap items-center justify-between gap-4">
          <Input
            placeholder="Search role name…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-[300px]"
          />

          <Button
            className="px-4 py-2 rounded text-white bg-blue-600 hover:bg-blue-700"
            onClick={() => {
              setCreateError("");
              setCreateForm({ name: "" });
              setSelectedPermissions([]);
              can("auth.add_group") && setOpenCreate(true);
            }}
          >
            <Plus className="mr-2 h-4 w-4" />
            Add New
          </Button>
        </div>

        {/* Table */}
        <Table>
          <TableHeader>
            <TableRow className="[&>th]:text-center">
              <TableHead className="!text-left">Role</TableHead>
              {/* Description column removed */}
              <TableHead>Users</TableHead>
              <TableHead>Active</TableHead>
              <TableHead>Action</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && (
              <TableRow>
                <TableCell colSpan={4} className="py-4 text-center text-gray-500 dark:text-gray-300">
                  Loading...
                </TableCell>
              </TableRow>
            )}

            {!loading && pageError && (
              <TableRow>
                <TableCell colSpan={4} className="py-4 text-center text-red-500">
                  {pageError}
                </TableCell>
              </TableRow>
            )}

            {!loading && !pageError && filtered.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} className="py-4 text-center text-gray-500 dark:text-gray-300">
                  No roles found
                </TableCell>
              </TableRow>
            )}

            {!loading &&
              !pageError &&
              filtered.map((g) => (
                <TableRow
                  key={g.id}
                  className="text-center text-base font-medium text-dark dark:text-white"
                >
                  <TableCell className="!text-left">{g.name}</TableCell>
                  <TableCell>{typeof g.users_count === "number" ? g.users_count : 0}</TableCell>
                  <TableCell>
                    <span
                      className={`px-2 py-1 rounded-full text-xs font-semibold ${
                        g.is_active ? "bg-green-200 text-green-800" : "bg-gray-200 text-gray-800"
                      }`}
                    >
                      {g.is_active ? "Active" : "Inactive"}
                    </span>
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="mx-auto flex items-center gap-2"
                      onClick={() => openDetailsModal(g)}
                      title="View / Edit / Delete"
                    >
                      <Settings className="h-4 w-4 text-blue-600" />
                      Manage
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
          </TableBody>
        </Table>
      </div>

      {/* Create Role Modal */}
      <AnimatedModal
        open={openCreate}
        onClose={() => {
          setOpenCreate(false);
          setCreateForm({ name: "" });
          setSelectedPermissions([]);
        }}
        title="Add New Role (Group)"
        maxWidthClassName="max-w-4xl"
      >
        <form className="space-y-4" onSubmit={handleCreate}>
          <div>
            <label className="mb-1 block text-sm font-medium">Role Name *</label>
            <Input
              placeholder="Role name"
              value={createForm.name}
              onChange={(e) => setCreateForm((s) => ({ ...s, name: e.target.value }))}
              required
            />
          </div>
          
          <div>
            <label className="mb-2 block text-sm font-medium">Permissions</label>
            {loadingPermissions ? (
              <div className="text-sm text-gray-500">Loading permissions...</div>
            ) : (
              <div className="max-h-96 overflow-y-auto rounded border border-gray-300 p-3 dark:border-dark-3 dark:bg-dark-2">
                {allPermissions.length === 0 ? (
                  <div className="text-sm text-gray-500">No permissions available</div>
                ) : (
                  <div className="space-y-2">
                    {Object.entries(
                      allPermissions.reduce((acc: Record<string, Permission[]>, perm) => {
                        const key = `${perm.content_type__app_label}.${perm.content_type__model}`;
                        if (!acc[key]) acc[key] = [];
                        acc[key].push(perm);
                        return acc;
                      }, {})
                    ).map(([model, perms]) => (
                      <div key={model} className="border-b border-gray-200 pb-2 last:border-0 dark:border-dark-3">
                        <div className="mb-1 text-xs font-semibold text-gray-600 dark:text-gray-400">
                          {model}
                        </div>
                        <div className="ml-2 space-y-1">
                          {perms.map((perm) => (
                            <label
                              key={perm.id}
                              className="flex items-center gap-2 text-sm"
                            >
                              <input
                                type="checkbox"
                                checked={selectedPermissions.includes(perm.id)}
                                onChange={(e) => {
                                  if (e.target.checked) {
                                    setSelectedPermissions([...selectedPermissions, perm.id]);
                                  } else {
                                    setSelectedPermissions(
                                      selectedPermissions.filter((id) => id !== perm.id)
                                    );
                                  }
                                }}
                                disabled={creating}
                                className="rounded"
                              />
                              <span className="text-xs">{perm.name}</span>
                            </label>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
          
          {createError && <div className="text-sm text-red-500">{createError}</div>}
          <Button
            type="submit"
            className="w-full bg-blue-600 text-white hover:bg-blue-700"
            disabled={creating}
          >
            {creating ? "Creating..." : "Create Role"}
          </Button>
        </form>
      </AnimatedModal>

      {/* Details / Edit / Delete Modal */}
      <AnimatedModal
        open={openDetails}
        onClose={() => {
          setOpenDetails(false);
          setSelectedPermissions([]);
        }}
        title={selected ? `Manage Role — ${selected.name}` : "Manage Role"}
        maxWidthClassName="max-w-4xl"
      >
        {!selected ? (
          <div className="text-sm text-gray-500 dark:text-dark-6">No role selected.</div>
        ) : (
          <form className="space-y-4" onSubmit={handleUpdate}>
            <div className="grid grid-cols-1 gap-3">
              <label className="text-sm font-medium">Role Name</label>
              <Input
                value={editForm.name}
                onChange={(e) => setEditForm((s) => ({ ...s, name: e.target.value }))}
                disabled={editing}
              />
            </div>

            <div>
              <label className="mb-2 block text-sm font-medium">Permissions</label>
              {loadingPermissions ? (
                <div className="text-sm text-gray-500">Loading permissions...</div>
              ) : (
                <div className="max-h-96 overflow-y-auto rounded border border-gray-300 p-3 dark:border-dark-3 dark:bg-dark-2">
                  {allPermissions.length === 0 ? (
                    <div className="text-sm text-gray-500">No permissions available</div>
                  ) : (
                    <div className="space-y-2">
                      {Object.entries(
                        allPermissions.reduce((acc: Record<string, Permission[]>, perm) => {
                          const key = `${perm.content_type__app_label}.${perm.content_type__model}`;
                          if (!acc[key]) acc[key] = [];
                          acc[key].push(perm);
                          return acc;
                        }, {})
                      ).map(([model, perms]) => (
                        <div key={model} className="border-b border-gray-200 pb-2 last:border-0 dark:border-dark-3">
                          <div className="mb-1 text-xs font-semibold text-gray-600 dark:text-gray-400">
                            {model}
                          </div>
                          <div className="ml-2 space-y-1">
                            {perms.map((perm) => (
                              <label
                                key={perm.id}
                                className="flex items-center gap-2 text-sm"
                              >
                                <input
                                  type="checkbox"
                                  checked={selectedPermissions.includes(perm.id)}
                                  onChange={(e) => {
                                    if (e.target.checked) {
                                      setSelectedPermissions([...selectedPermissions, perm.id]);
                                    } else {
                                      setSelectedPermissions(
                                        selectedPermissions.filter((id) => id !== perm.id)
                                      );
                                    }
                                  }}
                                  disabled={editing}
                                  className="rounded"
                                />
                                <span className="text-xs">{perm.name}</span>
                              </label>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>

            {detailsError && <div className="text-sm text-red-500">{detailsError}</div>}

            <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
              <div className="flex gap-2">
                <Button
                  type="submit"
                  className="bg-blue-600 text-white hover:bg-blue-700"
                  disabled={editing}
                >
                  {editing ? "Saving..." : "Save Changes"}
                </Button>

                <Button
                  type="button"
                  className={`${confirmDelete ? "bg-red-700" : "bg-red-600"} text-white hover:bg-red-700`}
                  onClick={() => (confirmDelete ? handleDelete() : can("auth.delete_group") && setConfirmDelete(true))}
                  disabled={deleting || editing}
                >
                  {deleting ? "Deleting..." : confirmDelete ? "Click to Confirm" : "Delete"}
                </Button>
              </div>

              <div className="text-xs text-gray-500 dark:text-dark-6">
                Members: {typeof selected.users_count === "number" ? selected.users_count : 0}
              </div>
            </div>
          </form>
        )}
      </AnimatedModal>

      {/* Success Modal */}
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
