"use client";

import { useChiroAuth } from "@/components/ChiroAuthProvider";
import { getCachedAccessToken } from "@/services/auth-session";
import { authFetch } from "@/services/auth-http";
import { Logo } from "@/components/logo";
import { cn } from "@/lib/utils";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, useCallback } from "react";
import { NAV_DATA } from "./data";
import { defaultRouteForRole, slugFromRole } from "@/lib/role";
import { ArrowLeftIcon, ChevronUp } from "./icons";
import { MenuItem } from "./menu-item";
import { useSidebarContext } from "./sidebar-context";
import { useTranslation } from "@/hooks/useTranslation";

export function Sidebar() {
  const { can } = useChiroAuth();
  const pathname = usePathname();
  const { setIsOpen, isOpen, isMobile, toggleSidebar } = useSidebarContext();
  const { t } = useTranslation();
  const [expandedItems, setExpandedItems] = useState<string[]>([]);
  
  // Translation mapping function
  const translateMenuTitle = (title: string): string => {
    const translationMap: Record<string, string> = {
      "Dashboard": t("nav", "dashboard"),
      "User Management": t("nav", "userManagement"),
      "User": t("nav", "user"),
      "Role": t("nav", "role"),
      "Office": t("nav", "office"),
      "Complaint / Appeal": t("nav", "complaintAppeal"),
      "Transfers": t("nav", "transfers"),
      "My Assigned Cases": t("nav", "myAssigned"),
      "Feedback / Appeal": t("nav", "feedbackAppeal"),
      "Reports": t("nav", "reports"),
      "Announcements": t("nav", "announcements"),
      "Help & Guidelines": t("nav", "help"),
      "System Settings": t("nav", "systemSettings"),
      "MAIN MENU": t("nav", "mainMenu"),
    };
    return translationMap[title] || title;
  };

  const toggleExpanded = useCallback((title: string) => {
    setExpandedItems((prev) => {
      // If clicking the same item that's already expanded, close it
      if (prev.includes(title)) {
        return [];
      }
      // Otherwise, close any other open menu and open the clicked one
      return [title];
    });
  }, []);

  // Keep collapsible open when its subpage is active
  useEffect(() => {
    NAV_DATA.some((section) => {
      return section.items.some((item) => {
        if (item.items && item.items.length > 0) {
          return item.items.some((subItem) => {
            if (subItem.url === pathname) {
              // Only update if the parent menu is not already expanded
              setExpandedItems((prev) => {
                if (!prev.includes(item.title)) {
                  return [item.title];
                }
                return prev;
              });
              return true;
            }
            return false;
          });
        }
        return false;
      });
    });
  }, [pathname]);

  // Get user groups from localStorage (dynamic role checking)
  const [userGroups, setUserGroups] = useState<string[]>([]);
  const [isLoadingGroups, setIsLoadingGroups] = useState(true);

  useEffect(() => {
    const loadUserGroups = async () => {
      if (typeof window === "undefined") {
        setIsLoadingGroups(false);
        return;
      }

      // Always fetch from API to ensure we have the latest groups
      const token = getCachedAccessToken();
      if (token) {
        try {
          const API_URL = process.env.NEXT_PUBLIC_API_URL;
          const res = await authFetch(`${API_URL}/auth/me/`, {
            headers: { Authorization: `Bearer ${token}` },
            cache: "no-store",
          });
          if (res.ok) {
            const data = await res.json();
            const groups = (data.user_groups || []).map((g: string) => g).filter(Boolean);
            setUserGroups(groups);
            localStorage.setItem("user_groups", JSON.stringify(groups));
            console.log("✅ Sidebar loaded user groups from API:", groups);
            setIsLoadingGroups(false);
            return;
          } else {
            console.error("❌ Failed to fetch user groups:", res.status, res.statusText);
          }
        } catch (e) {
          console.error("❌ Failed to load user groups:", e);
        }
      }

      // Fallback to localStorage if API fails
      try {
        const raw = localStorage.getItem("user_groups");
        if (raw) {
          const parsed = JSON.parse(raw);
          if (Array.isArray(parsed) && parsed.length > 0) {
            const groups = parsed
              .map((g) => (typeof g === "string" ? g : g?.name))
              .filter(Boolean) as string[];
            setUserGroups(groups);
          }
        }
      } catch {
        // Ignore errors
      }
      
      setIsLoadingGroups(false);
    };

    loadUserGroups();
    
    // Reload when pathname changes (e.g., after login redirect)
    const handleFocus = () => {
      loadUserGroups();
    };
    window.addEventListener("focus", handleFocus);
    
    return () => {
      window.removeEventListener("focus", handleFocus);
    };
  }, [pathname]);

  // Fallback: also check role from localStorage if user_groups not loaded
  const roleFromStorage =
    typeof window !== "undefined" ? localStorage.getItem("role") : null;

  // Check if user has Admin role (full system access)
  const hasAdmin = userGroups.includes("Admin");
  
  // Check if user has Mayor Office role (highest level - should have all access)
  const hasMayorOffice = userGroups.includes("Mayor Office");
  
  // Check if user has any staff role (non-citizen)
  const hasStaffRole = userGroups.some((role) => role !== "Citizen") || 
    (roleFromStorage && roleFromStorage !== "Citizen");

  // Debug: Log user groups for troubleshooting
  useEffect(() => {
    if (userGroups.length > 0) {
      console.log("Sidebar - User Groups:", userGroups);
      console.log("Sidebar - Has Admin:", hasAdmin);
      console.log("Sidebar - Has Mayor Office:", hasMayorOffice);
    }
  }, [userGroups, hasAdmin, hasMayorOffice]);

  const filterByRole = (items: Array<{ allowedRoles?: string[] } & Record<string, any>>): Array<{ allowedRoles?: string[] } & Record<string, any>> => {
    const required: Record<string, string> = {
      "/dashboard": "cas_app.view_case", "/users": "cas_app.view_user", "/roles": "auth.view_group",
      "/offices": "cas_app.view_office", "/cases": "cas_app.view_case", "/cases/activity": "cas_app.view_transfer",
      "/cases/my-assigned": "cas_app.view_assignment", "/feedback-appeal": "cas_app.view_casefeedback",
      "/reports": "cas_app.view_case", "/settings": "auth.change_group",
    };
    return items.filter(item => {
      if (item.items?.length) return filterByRole(item.items).length > 0;
      if (item.url && required[item.url]) return can(required[item.url]);
      if (item.title === "Announcements") return can("cas_app.view_announcement");
      return !item.allowedRoles?.length;
    });
  };

  // Prevent body scroll when sidebar is open on mobile
  useEffect(() => {
    if (isMobile && isOpen) {
      // Disable body scroll
      document.body.style.overflow = "hidden";
      // Prevent scroll on touch devices
      document.body.style.position = "fixed";
      document.body.style.width = "100%";
    } else {
      // Re-enable body scroll
      document.body.style.overflow = "";
      document.body.style.position = "";
      document.body.style.width = "";
    }

    // Cleanup on unmount
    return () => {
      document.body.style.overflow = "";
      document.body.style.position = "";
      document.body.style.width = "";
    };
  }, [isMobile, isOpen]);

  return (
    <>
      {/* Mobile Overlay - Dark backdrop to cover background content */}
      {isMobile && isOpen && (
        <div
          className="fixed inset-0 z-[45] bg-black/70 backdrop-blur-sm transition-opacity duration-300"
          onClick={() => setIsOpen(false)}
          onTouchStart={(e) => {
            // Prevent touch events from passing through
            e.preventDefault();
          }}
          aria-hidden="true"
          role="button"
          tabIndex={-1}
        />
      )}

      <aside
        className={cn(
          "max-w-[290px] overflow-hidden border-r border-primary/20 bg-gradient-to-b from-primary/5 via-white to-white transition-[width] duration-200 ease-linear dark:border-primary/30 dark:from-primary/10 dark:via-gray-dark dark:to-gray-dark",
          isMobile ? "fixed bottom-0 top-0 z-[50]" : "sticky top-0 h-screen",
          isOpen ? "w-full" : "w-0",
        )}
        aria-label="Main navigation"
        aria-hidden={!isOpen}
        inert={!isOpen}
      >
        <div className="flex h-full flex-col py-10 pl-[25px] pr-[7px]">
          <div className="relative pr-4.5">
            <Link
              href={"/"}
              onClick={() => isMobile && toggleSidebar()}
              className="px-0 py-2.5 min-[850px]:py-0"
            >
              <Logo />
            </Link>

            {isMobile && (
              <button
                onClick={toggleSidebar}
                className="absolute left-3/4 right-4.5 top-1/2 -translate-y-1/2 text-right"
              >
                <span className="sr-only">Close Menu</span>

                <ArrowLeftIcon className="ml-auto size-7" />
              </button>
            )}
          </div>

          {/* Navigation */}
          <div className="custom-scrollbar mt-6 flex-1 overflow-y-auto pr-3 min-[850px]:mt-10">
            {isLoadingGroups ? (
              <div className="flex items-center justify-center py-8">
                <div className="text-sm text-dark-6 dark:text-dark-6">{t("nav", "loading")}</div>
              </div>
            ) : (
              NAV_DATA.map((section) => (
                <div key={section.label} className="mb-6">
                  <h2 className="mb-5 text-sm font-semibold text-primary/80 dark:text-primary/70">
                    {translateMenuTitle(section.label)}
                  </h2>

                  <nav role="navigation" aria-label={section.label}>
                    <ul className="space-y-2">
                      {filterByRole(section.items).map((item) => (
                      <li key={item.title}>
                        {item.items.length ? (
                          <div>
                            <MenuItem
                              isActive={item.items.some(
                                (subItem: { url?: string }) =>
                                  subItem.url === pathname,
                              )}
                              onClick={() => toggleExpanded(item.title)}
                            >
                              <item.icon
                                className="size-6 shrink-0"
                                aria-hidden="true"
                              />

                              <span>{translateMenuTitle(item.title)}</span>

                              <ChevronUp
                                className={cn(
                                  "ml-auto rotate-180 transition-transform duration-200",
                                  expandedItems.includes(item.title) &&
                                    "rotate-0",
                                )}
                                aria-hidden="true"
                              />
                            </MenuItem>

                            {expandedItems.includes(item.title) && (
                              <ul
                                className="ml-9 mr-0 space-y-1.5 pb-[15px] pr-0 pt-2"
                                role="menu"
                              >
                                {filterByRole(item.items).map((subItem) => (
                                  <li key={subItem.title} role="none">
                                    <MenuItem
                                      as="link"
                                      href={
                                        subItem.url === "/dashboard" && (userGroups.length > 0 || roleFromStorage)
                                          ? defaultRouteForRole(userGroups[0] || roleFromStorage)
                                          : subItem.url
                                      }
                                      isActive={pathname === subItem.url}
                                    >
                                      <span>{translateMenuTitle(subItem.title)}</span>
                                    </MenuItem>
                                  </li>
                                ))}
                              </ul>
                            )}
                          </div>
                        ) : (
                          (() => {
                            const href =
                              "url" in item
                                ? item.url + ""
                                : "/" +
                                  item.title.toLowerCase().split(" ").join("-");
                            const finalHref =
                              href === "/dashboard" && (userGroups.length > 0 || roleFromStorage)
                                ? defaultRouteForRole(userGroups[0] || roleFromStorage)
                                : href;

                            return (
                              <MenuItem
                                className="flex items-center gap-3 py-3"
                                as="link"
                                href={finalHref}
                                isActive={pathname === href}
                              >
                                <item.icon
                                  className="size-6 shrink-0"
                                  aria-hidden="true"
                                />

                                <span>{translateMenuTitle(item.title)}</span>
                              </MenuItem>
                            );
                          })()
                        )}
                      </li>
                      ))}
                    </ul>
                  </nav>
                </div>
              ))
            )}
          </div>
        </div>
      </aside>
    </>
  );
}

