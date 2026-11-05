"use client";

import { useChiroAuth } from "@/components/ChiroAuthProvider";
import { getCachedAccessToken } from "@/services/auth-session";
import { authFetch } from "@/services/auth-http";
import { useEffect, useMemo, useState, useCallback } from "react";
import Breadcrumb from "@/components/Breadcrumbs/Breadcrumb";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { AnimatedModal } from "@/components/ui/animated-modal";
import { SuccessModal } from "@/components/ui/success-modal";
import { Settings, ArrowRight, RefreshCcw, ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";

/* ===================== Types ===================== */

type ApiOffice = { id: number | string; name: string };

type ApiUser = {
  id: number | string;
  email?: string | null;
  first_name?: string | null;
  last_name?: string | null;
  username?: string | null;
  groups?: Array<{ name: string } | string> | null;
};

type ApiCase = {
  id: number | string;
  title?: string;
  status?: string;
};

type TransferRecord = {
  id: number | string;
  case: number | string | ApiCase;
  case_id?: number | string;
  from_office?: number | string | ApiOffice | null;
  from_office_id?: number | string | null;
  to_office?: number | string | ApiOffice | null;
  to_office_id?: number | string | null;
  reason?: string | null;
  created_at?: string | null; // or timestamp if your API uses that
  timestamp?: string | null;
};

type AssignmentRecord = {
  id: number | string;
  case: number | string | ApiCase;
  case_id?: number | string;
  from_user?: number | string | ApiUser | null;
  from_user_id?: number | string | null;
  to_user?: number | string | ApiUser | null;
  to_user_id?: number | string | null;
  reason?: string | null;
  created_at?: string | null; // or timestamp if your API uses that
  timestamp?: string | null;
};

/* ===================== Helpers ===================== */

const nameOfUser = (u?: ApiUser | string | number | null, usersList?: ApiUser[]) => {
  if (!u) return "—";
  
  // If it's already an object with user data, use it
  if (typeof u === "object" && u !== null && "first_name" in u) {
    const full = `${u.first_name || ""} ${u.last_name || ""}`.trim();
    return full || u.email || u.username || String(u.id);
  }
  
  // If it's an ID (string or number) and we have a users list, look it up
  if ((typeof u === "string" || typeof u === "number") && usersList) {
    const found = usersList.find((user) => String(user.id) === String(u));
    if (found) {
      const full = `${found.first_name || ""} ${found.last_name || ""}`.trim();
      return full || found.email || found.username || String(found.id);
    }
  }
  
  // Fallback: return the ID as string
  return String(u);
};

const nameOfOffice = (o?: ApiOffice | string | number | null, officesList?: ApiOffice[]) => {
  if (!o) return "—";
  
  // If it's already an object with office data, use it
  if (typeof o === "object" && o !== null && "name" in o) {
    return o.name;
  }
  
  // If it's an ID (string or number) and we have an offices list, look it up
  if ((typeof o === "string" || typeof o === "number") && officesList) {
    const found = officesList.find((office) => String(office.id) === String(o));
    if (found) {
      return found.name;
    }
  }
  
  // Fallback: return the ID as string
  return String(o);
};

const caseIdOf = (r: TransferRecord | AssignmentRecord) =>
  (r as any).case_id ?? (typeof (r as any).case === "object" ? (r as any).case.id : (r as any).case);

const caseTitleOf = (r: TransferRecord | AssignmentRecord) => {
  const c = (r as any).case;
  return typeof c === "object" && c?.title ? c.title : `Case #${caseIdOf(r)}`;
};

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

/* ===================== Page ===================== */

export default function CaseActivityPage() {
  const { can } = useChiroAuth();
  const API_URL = process.env.NEXT_PUBLIC_API_URL;
  const token = typeof window !== "undefined" ? getCachedAccessToken() : null;
  const headers: HeadersInit = useMemo(() => (token ? { Authorization: `Bearer ${token}` } : {}) as HeadersInit, [token]);

  // Current user context
  const currentUserId = typeof window !== "undefined" ? localStorage.getItem("user_id") || "" : "";
  const currentOfficeId = typeof window !== "undefined" ? localStorage.getItem("office_id") || "" : "";

  // Which list to show
  const [mode, setMode] = useState<"transfer" | "assign">("transfer");

  // Data
  const [transfers, setTransfers] = useState<TransferRecord[]>([]);
  const [assignments, setAssignments] = useState<AssignmentRecord[]>([]);

  // Options for manage actions
  const [offices, setOffices] = useState<ApiOffice[]>([]);
  const [members, setMembers] = useState<ApiUser[]>([]); // Non-Citizen users for assignment dropdown
  const [allUsers, setAllUsers] = useState<ApiUser[]>([]); // All users for lookup (including Citizens)

  // UX
  const [loadingList, setLoadingList] = useState(false);
  const [loadingOptions, setLoadingOptions] = useState(false);
  const [error, setError] = useState("");

  // Manage modal
  const [manageOpen, setManageOpen] = useState(false);
  const [selectedRow, setSelectedRow] = useState<TransferRecord | AssignmentRecord | null>(null);
  const [selectedOfficeId, setSelectedOfficeId] = useState<string>("");
  const [selectedMemberId, setSelectedMemberId] = useState<string>("");
  const [reason, setReason] = useState<string>("");

  // Delete
  const [deleting, setDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  // Success modal
  const [successOpen, setSuccessOpen] = useState(false);
  const [successMsg, setSuccessMsg] = useState("");

  // Pagination
  const [currentPage, setCurrentPage] = useState(1);
  const itemsPerPage = 15;

  const officeOptions = useMemo(
    () => offices.map((o) => ({ id: String(o.id), label: o.name })).sort((a, b) => a.label.localeCompare(b.label)),
    [offices],
  );

  const memberOptions = useMemo(
    () =>
      members
        .map((u) => {
          const full = `${u.first_name || ""} ${u.last_name || ""}`.trim();
          return { id: String(u.id), label: full || u.email || u.username || String(u.id) };
        })
        .sort((a, b) => a.label.localeCompare(b.label)),
    [members],
  );

  /* ---------- Load lists ---------- */

  const loadLists = async () => {
    if (!API_URL || !token) return;
    try {
      setLoadingList(true);
      setError("");

      // Adjust endpoints to your API if needed:
      const transfersUrl =
        currentOfficeId
          ? `${API_URL}/transfers/?from_office_id=${encodeURIComponent(currentOfficeId)}`
          : `${API_URL}/transfers/`;

      const assignmentsUrl =
        currentUserId
          ? `${API_URL}/assignments/?from_user_id=${encodeURIComponent(currentUserId)}`
          : `${API_URL}/assignments/`;

      const [t, a] = await Promise.all([
        fetchAllPaginated<TransferRecord>(transfersUrl, headers),
        fetchAllPaginated<AssignmentRecord>(assignmentsUrl, headers),
      ]);

      // Client-side fallback filtering if the API didn't filter
      const filteredT = currentOfficeId
        ? t.filter((r) =>
            String((r.from_office_id ?? (typeof r.from_office === "object" ? r.from_office?.id : r.from_office))) ===
            String(currentOfficeId),
          )
        : t;

      const filteredA = currentUserId
        ? a.filter((r) =>
            String((r.from_user_id ?? (typeof r.from_user === "object" ? r.from_user?.id : r.from_user))) ===
            String(currentUserId),
          )
        : a;

      setTransfers(filteredT);
      setAssignments(filteredA);
    } catch (e: any) {
      setError(e?.message || "Failed to load data");
    } finally {
      setLoadingList(false);
    }
  };

  /* ---------- Load options for manage actions ---------- */

  const loadOptions = async () => {
    if (!API_URL || !token) return;
    try {
      setLoadingOptions(true);

      const [officesList, usersList] = await Promise.all([
        can("cas_app.view_office") ? fetchAllPaginated<ApiOffice>(`${API_URL}/offices/`, headers) : Promise.resolve([]),
        can("cas_app.add_assignment") ? fetchAllPaginated<ApiUser>(`${API_URL}/assignments/assignable-users/`, headers) : Promise.resolve([]),
      ]);

      // Members: exclude Citizen (for assignment dropdown)
      const filteredUsers = usersList.filter((u) => {
        const groups = (u?.groups || [])
          .map((g) => (typeof g === "string" ? g : g?.name))
          .filter(Boolean) as string[];
        return !groups.includes("Citizen");
      });

      setOffices(officesList);
      setMembers(filteredUsers);
      setAllUsers(usersList); // Store all users for lookup purposes
    } catch {
      setOffices([]);
      setMembers([]);
    } finally {
      setLoadingOptions(false);
    }
  };

  useEffect(() => {
    loadLists();
    loadOptions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ---------- Manage handlers ---------- */

  const openManage = (row: TransferRecord | AssignmentRecord, kind: "transfer" | "assign") => {
    setSelectedRow(row);
    // Prefill the last chosen destination + reason:
    if (kind === "transfer") {
      const transferRow = row as TransferRecord;
      const currentTo =
        transferRow.to_office_id ??
        (typeof transferRow.to_office === "object" ? transferRow.to_office?.id : transferRow.to_office) ??
        "";
      setSelectedOfficeId(currentTo ? String(currentTo) : "");
    } else {
      const assignRow = row as AssignmentRecord;
      const currentTo =
        assignRow.to_user_id ??
        (typeof assignRow.to_user === "object" ? assignRow.to_user?.id : assignRow.to_user) ??
        "";
      setSelectedMemberId(currentTo ? String(currentTo) : "");
    }
    setReason((row as any).reason || ""); // ✅ prefill reason
    setConfirmDelete(false);
    setManageOpen(true);
  };

  const TRANSFER_URL = (cid: string | number) => `${API_URL}/cases/${cid}/transfer/`;
  const ASSIGN_URL = (cid: string | number) => `${API_URL}/cases/${cid}/assign/`;

  const handleReTransfer = async () => {
    if (!selectedRow || !token) return;
    const cid = caseIdOf(selectedRow);
    if (!cid) return;
    if (!selectedOfficeId) return;
    const currentOfficeId = typeof window !== "undefined" ? localStorage.getItem("office_id") || "" : "";
    if (!currentOfficeId) return setError("Your office_id is missing.");
    if (!reason.trim()) return;

    const payload = {
      case_id: String(cid),
      from_office_id: String(currentOfficeId),
      to_office_id: String(selectedOfficeId),
      reason: reason.trim(),
    };

    const res = await authFetch(TRANSFER_URL(cid), {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const msg = await res.text();
      throw new Error(msg || `Transfer failed: ${res.status}`);
    }
  };

  const handleReAssign = async () => {
    if (!selectedRow || !token) return;
    const cid = caseIdOf(selectedRow);
    if (!cid) return;
    if (!selectedMemberId) return;
    const currentUserId = typeof window !== "undefined" ? localStorage.getItem("user_id") || "" : "";
    if (!currentUserId) return setError("Your user_id is missing.");
    if (!reason.trim()) return;

    const payload = {
      case_id: String(cid),
      from_user_id: String(currentUserId),
      to_user_id: String(selectedMemberId),
      reason: reason.trim(),
    };

    const res = await authFetch(ASSIGN_URL(cid), {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const msg = await res.text();
      throw new Error(msg || `Assign failed: ${res.status}`);
    }
  };

  const onConfirmManage = async () => {
    try {
      if (mode === "transfer") {
        await handleReTransfer();
        setSuccessMsg("Case re-transferred successfully.");
      } else {
        await handleReAssign();
        setSuccessMsg("Case re-assigned successfully.");
      }
      setManageOpen(false);
      setSuccessOpen(true);
      setTimeout(() => setSuccessOpen(false), 3000);
      await loadLists();
    } catch (e: any) {
      setError(e?.message || "Operation failed");
    }
  };

  // Delete a transfer/assignment record (adjust endpoints if your API differs)
  const deleteEndpoint = (row: TransferRecord | AssignmentRecord) =>
    mode === "transfer" ? `${API_URL}/transfers/${row.id}/` : `${API_URL}/assignments/${row.id}/`;

  const onDeleteRecord = async () => {
    if (!selectedRow || !API_URL || !token) return;
    try {
      setDeleting(true);
      const res = await authFetch(deleteEndpoint(selectedRow), {
        method: "DELETE",
        headers,
      });
      if (!res.ok && res.status !== 204) {
        const msg = await res.text();
        throw new Error(msg || `Delete failed: ${res.status}`);
      }
      setManageOpen(false);
      setSuccessMsg(mode === "transfer" ? "Transfer deleted." : "Assignment deleted.");
      setSuccessOpen(true);
      setTimeout(() => setSuccessOpen(false), 3000);
      await loadLists();
    } catch (e: any) {
      setError(e?.message || "Delete failed");
    } finally {
      setDeleting(false);
      setConfirmDelete(false);
    }
  };

  /* ---------- Derived rows ---------- */

  const rows = mode === "transfer" ? transfers : assignments;

  // Pagination calculations
  const totalPages = Math.ceil(rows.length / itemsPerPage);
  const startIndex = (currentPage - 1) * itemsPerPage;
  const endIndex = startIndex + itemsPerPage;
  const paginatedData = rows.slice(startIndex, endIndex);

  // Reset to page 1 when mode changes
  useEffect(() => {
    setCurrentPage(1);
  }, [mode]);

  // Build modal title with case title included
  const modalTitle =
    !selectedRow
      ? mode === "transfer" ? "Re-Transfer Case" : "Re-Assign Case"
      : `${mode === "transfer" ? "Re-Transfer" : "Re-Assign"} — ${caseTitleOf(selectedRow)}`;
  
      
  
  /* ===================== Render ===================== */

  return (
    <>
      <Breadcrumb pageName="Case Activity" />

      <div className={cn("rounded-[10px] bg-white p-5 shadow-1 dark:bg-gray-dark dark:shadow-card")}>
        {/* Top controls */}
        <div className="mb-4 flex flex-wrap items-center justify-between gap-4">
          <div className="flex gap-2">
            <Button
              variant={mode === "transfer" ? "default" : "outline"}
              className={mode === "transfer" ? "bg-blue-600 text-white hover:bg-blue-700" : ""}
              onClick={() => setMode("transfer")}
            >
              Transfers
            </Button>
            <Button
              variant={mode === "assign" ? "default" : "outline"}
              className={mode === "assign" ? "bg-blue-600 text-white hover:bg-blue-700" : ""}
              onClick={() => setMode("assign")}
            >
              Assignments
            </Button>

            <Button variant="ghost" onClick={loadLists} title="Refresh">
              <RefreshCcw className="h-4 w-4" />
            </Button>
          </div>

          <Link href="/cases">
            <Button className="bg-blue-600 text-white hover:bg-blue-700">
              Transfer / Assign more
              <ArrowRight className="ml-2 h-4 w-4" />
            </Button>
          </Link>
        </div>

        {/* Table */}
        <Table>
          <TableHeader>
            <TableRow className="[&>th]:text-center">
              <TableHead className="!text-left">Case</TableHead>
              {mode === "transfer" ? (
                <>
                  <TableHead>From Office</TableHead>
                  <TableHead>To Office</TableHead>
                </>
              ) : (
                <>
                  <TableHead>From User</TableHead>
                  <TableHead>To User</TableHead>
                </>
              )}
              <TableHead>Reason</TableHead>
              <TableHead>Date</TableHead>
              <TableHead>Action</TableHead>
            </TableRow>
          </TableHeader>

          <TableBody>
            {loadingList && (
              <TableRow>
                <TableCell colSpan={6} className="py-4 text-center text-gray-500 dark:text-gray-300">
                  Loading…
                </TableCell>
              </TableRow>
            )}

            {!loadingList && error && (
              <TableRow>
                <TableCell colSpan={6} className="py-4 text-center text-red-500">
                  {error}
                </TableCell>
              </TableRow>
            )}

            {!loadingList && !error && rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="py-4 text-center text-gray-500 dark:text-gray-300">
                  No records found
                </TableCell>
              </TableRow>
            )}

            {!loadingList &&
              !error &&
              paginatedData.map((r) => (
                <TableRow key={(r as any).id} className="text-center text-base font-medium text-dark dark:text-white">
                  <TableCell className="!text-left">
                    <div className="flex items-center justify-between gap-2">
                      <span>{caseTitleOf(r)}</span>
                      <Link href={`/cases/${caseIdOf(r)}/view`} className="text-primary text-sm underline">
                        View
                      </Link>
                    </div>
                  </TableCell>

                  {mode === "transfer" ? (
                    <>
                      <TableCell>
                        {nameOfOffice(
                          (r as TransferRecord).from_office ?? (r as TransferRecord).from_office_id,
                          offices
                        )}
                      </TableCell>
                      <TableCell>
                        {nameOfOffice(
                          (r as TransferRecord).to_office ?? (r as TransferRecord).to_office_id,
                          offices
                        )}
                      </TableCell>
                    </>
                  ) : (
                    <>
                      <TableCell>
                        {nameOfUser(
                          (r as AssignmentRecord).from_user ?? (r as AssignmentRecord).from_user_id,
                          allUsers
                        )}
                      </TableCell>
                      <TableCell>
                        {nameOfUser(
                          (r as AssignmentRecord).to_user ?? (r as AssignmentRecord).to_user_id,
                          allUsers
                        )}
                      </TableCell>
                    </>
                  )}

                  <TableCell className="truncate max-w-[280px]">{(r as any).reason || "—"}</TableCell>
                  <TableCell>
                    {(r as any).created_at
                      ? String((r as any).created_at).slice(0, 10)
                      : (r as any).timestamp
                      ? String((r as any).timestamp).slice(0, 10)
                      : "—"}
                  </TableCell>

                  <TableCell>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="mx-auto flex items-center gap-2"
                      onClick={() => openManage(r as any, mode)}
                      title="Manage"
                    >
                      <Settings className="h-4 w-4 text-blue-600" />
                      Manage
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
          </TableBody>
        </Table>

        {/* Pagination */}
        {!loadingList && !error && rows.length > itemsPerPage && (
          <div className="mt-4 flex items-center justify-between border-t border-stroke pt-4 dark:border-dark-3">
            <div className="text-sm text-gray-600 dark:text-gray-400">
              Showing {startIndex + 1} to {Math.min(endIndex, rows.length)} of {rows.length} {mode === "transfer" ? "transfers" : "assignments"}
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                disabled={currentPage === 1}
              >
                <ChevronLeft className="h-4 w-4" />
                Previous
              </Button>
              <div className="flex items-center gap-1">
                {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                  let pageNum;
                  if (totalPages <= 5) {
                    pageNum = i + 1;
                  } else if (currentPage <= 3) {
                    pageNum = i + 1;
                  } else if (currentPage >= totalPages - 2) {
                    pageNum = totalPages - 4 + i;
                  } else {
                    pageNum = currentPage - 2 + i;
                  }
                  return (
                    <Button
                      key={pageNum}
                      variant={currentPage === pageNum ? "default" : "outline"}
                      size="sm"
                      className={currentPage === pageNum ? "bg-blue-600 text-white" : ""}
                      onClick={() => setCurrentPage(pageNum)}
                    >
                      {pageNum}
                    </Button>
                  );
                })}
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                disabled={currentPage === totalPages}
              >
                Next
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* Manage Modal (re-transfer / re-assign) */}
      <AnimatedModal
        open={manageOpen}
        onClose={() => setManageOpen(false)}
        title={modalTitle} // ✅ shows "Re-Transfer — <Case Title>" or "Re-Assign — <Case Title>"
        maxWidthClassName="max-w-md"
      >
        {!selectedRow ? (
          <div className="text-sm text-gray-500 dark:text-dark-6">No record selected.</div>
        ) : (
          <div className="space-y-4">
            {mode === "transfer" ? (
              <div>
                <label className="mb-1 block text-sm font-medium">To Office</label>
                <select
                  className="w-full rounded border border-gray-300 p-2 dark:border-dark-3 dark:bg-dark-2"
                  value={selectedOfficeId}
                  onChange={(e) => setSelectedOfficeId(e.target.value)}
                >
                  <option value="">— Select —</option>
                  {officeOptions.map((o) => (
                    <option key={o.id} value={o.id}>{o.label}</option>
                  ))}
                </select>
              </div>
            ) : (
              <div>
                <label className="mb-1 block text-sm font-medium">Assign To</label>
                <select
                  className="w-full rounded border border-gray-300 p-2 dark:border-dark-3 dark:bg-dark-2"
                  value={selectedMemberId}
                  onChange={(e) => setSelectedMemberId(e.target.value)}
                >
                  <option value="">— Select —</option>
                  {memberOptions.map((m) => (
                    <option key={m.id} value={m.id}>{m.label}</option>
                  ))}
                </select>
              </div>
            )}

            <div>
              <label className="mb-1 block text-sm font-medium">Reason</label>
              <textarea
                className="w-full rounded border border-gray-300 p-2 dark:border-dark-3 dark:bg-dark-2"
                rows={3}
                placeholder={mode === "transfer" ? "Reason for transfer…" : "Reason for assignment…"}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex gap-2">
                <Button variant="ghost" onClick={() => setManageOpen(false)}>Cancel</Button>
                <Button
                  className={mode === "transfer" ? "bg-yellow-600 hover:bg-yellow-700 text-white" : "bg-blue-600 hover:bg-blue-700 text-white"}
                  onClick={onConfirmManage}
                  disabled={
                    mode === "transfer"
                      ? !selectedOfficeId || !reason.trim()
                      : !selectedMemberId || !reason.trim()
                  }
                >
                  {mode === "transfer" ? "Confirm Transfer" : "Confirm Assign"}
                </Button>
              </div>

              {/* Delete Area */}
              <div className="flex items-center gap-2">
                <Button
                  className={`${confirmDelete ? "bg-red-700" : "bg-red-600"} text-white hover:bg-red-700`}
                  onClick={() => (confirmDelete ? onDeleteRecord() : setConfirmDelete(true))}
                  disabled={deleting}
                >
                  {deleting ? "Deleting..." : confirmDelete ? "Click to Confirm" : "Delete"}
                </Button>
              </div>
            </div>
          </div>
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
