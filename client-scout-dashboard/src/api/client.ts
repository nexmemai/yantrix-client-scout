import {
  LeadDetail,
  NicheConfig,
  PaginatedLeads,
  PitchResponse,
} from "../lib/types";

export interface ApiSession {
  token: string;
  apiBaseUrl?: string;
}

interface RequestInitExtra extends RequestInit {
  query?: Record<string, string | number | undefined | null>;
}

function apiBaseUrl(session: ApiSession) {
  // Production is always same-origin through the dashboard Nginx /api proxy.
  if (!import.meta.env.DEV) {
    return "";
  }
  return session.apiBaseUrl || import.meta.env.VITE_API_BASE_URL || "";
}

function buildUrl(session: ApiSession, path: string, query?: RequestInitExtra["query"]) {
  const baseUrl = apiBaseUrl(session);
  const url = new URL(path, baseUrl ? (baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`) : window.location.origin);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== "") {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return baseUrl ? url.toString() : `${url.pathname}${url.search}`;
}

async function request<T>(
  session: ApiSession,
  path: string,
  init?: RequestInitExtra,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(buildUrl(session, path, init?.query), {
      ...init,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${session.token}`,
        "X-Yantrix-Token": session.token,
        ...(init?.headers ?? {}),
      },
    });
  } catch (error) {
    throw new Error(
      error instanceof TypeError
        ? "Network error: dashboard could not reach the API proxy at /api."
        : "Network error while contacting the API.",
    );
  }

  if (!response.ok) {
    const text = await response.text();
    if (response.status === 401 || response.status === 403) {
      throw new Error("Authentication failed. Check the shared token.");
    }
    throw new Error(text || `API request failed with status ${response.status}`);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  try {
    return (await response.json()) as T;
  } catch {
    throw new Error("API returned an invalid JSON response.");
  }
}

export const apiClient = {
  listLeads(session: ApiSession, query?: RequestInitExtra["query"]) {
    return request<PaginatedLeads>(session, "/api/v1/leads", { method: "GET", query });
  },
  getLead(session: ApiSession, leadId: string) {
    return request<LeadDetail>(session, `/api/v1/leads/${leadId}`, { method: "GET" });
  },
  regeneratePitch(session: ApiSession, leadId: string) {
    return request<PitchResponse>(session, `/api/v1/leads/${leadId}/pitch`, { method: "POST" });
  },
  listConfigs(session: ApiSession) {
    return request<NicheConfig[]>(session, "/api/v1/configs", { method: "GET" });
  },
  getConfig(session: ApiSession, niche: string) {
    return request<NicheConfig>(session, `/api/v1/configs/${niche}`, { method: "GET" });
  },
  upsertConfig(session: ApiSession, niche: string, payload: Pick<NicheConfig, "weights" | "prompt_template">) {
    return request<NicheConfig>(session, `/api/v1/configs/${niche}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },
  deleteConfig(session: ApiSession, niche: string) {
    return request<void>(session, `/api/v1/configs/${niche}`, { method: "DELETE" });
  },
};
