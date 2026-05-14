import {
  LeadDetail,
  NicheConfig,
  PaginatedLeads,
  PitchResponse,
} from "../lib/types";

export interface ApiSession {
  baseUrl: string;
  token: string;
}

interface RequestInitExtra extends RequestInit {
  query?: Record<string, string | number | undefined | null>;
}

function buildUrl(baseUrl: string, path: string, query?: RequestInitExtra["query"]) {
  const url = new URL(path, baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== "") {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return url.toString();
}

async function request<T>(
  session: ApiSession,
  path: string,
  init?: RequestInitExtra,
): Promise<T> {
  const response = await fetch(buildUrl(session.baseUrl, path, init?.query), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${session.token}`,
      "X-Yantrix-Token": session.token,
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `API request failed with status ${response.status}`);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
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
