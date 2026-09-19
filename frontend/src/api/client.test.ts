import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, onSessionEnded, unwrap } from "./client";
import { ApiError } from "./errors";
import { clearTokens, getAccessToken, getRefreshToken, setTokens } from "./tokens";

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const ME = { id: "u1", email: "ops@northfield.example" };

describe("API client token handling", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    setTokens("at_old", "rt_old");
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    clearTokens();
  });

  it("sends the access token", async () => {
    fetchMock.mockResolvedValueOnce(json(200, ME));
    await unwrap(api.GET("/api/v1/auth/me"));
    const request = fetchMock.mock.calls[0][0] as Request;
    expect(request.headers.get("Authorization")).toBe("Bearer at_old");
  });

  it("refreshes once on 401 and retries with the new token", async () => {
    fetchMock.mockImplementation(async (input: Request | string) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.endsWith("/auth/refresh")) return json(200, { access_token: "at_new", refresh_token: "rt_new" });
      const auth = (input as Request).headers.get("Authorization");
      return auth === "Bearer at_new" ? json(200, ME) : json(401, { error: { code: "UNAUTHENTICATED", message: "expired" } });
    });
    const me = await unwrap(api.GET("/api/v1/auth/me"));
    expect(me).toEqual(ME);
    expect(getAccessToken()).toBe("at_new");
    expect(getRefreshToken()).toBe("rt_new"); // the rotated refresh token replaces the old one
  });

  it("parallel requests share one refresh (refresh tokens are single-use)", async () => {
    let refreshes = 0;
    fetchMock.mockImplementation(async (input: Request | string) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.endsWith("/auth/refresh")) {
        refreshes += 1;
        await new Promise((resolve) => setTimeout(resolve, 20));
        return json(200, { access_token: "at_new", refresh_token: "rt_new" });
      }
      const auth = (input as Request).headers.get("Authorization");
      return auth === "Bearer at_new" ? json(200, ME) : json(401, {});
    });
    await Promise.all([unwrap(api.GET("/api/v1/auth/me")), unwrap(api.GET("/api/v1/auth/me")), unwrap(api.GET("/api/v1/auth/me"))]);
    expect(refreshes).toBe(1);
  });

  it("ends the session when the refresh fails", async () => {
    const ended = vi.fn();
    const unsubscribe = onSessionEnded(ended);
    fetchMock.mockImplementation(async (input: Request | string) => {
      const url = typeof input === "string" ? input : input.url;
      return url.endsWith("/auth/refresh") ? json(401, {}) : json(401, { error: { code: "UNAUTHENTICATED", message: "Session expired" } });
    });
    await expect(unwrap(api.GET("/api/v1/auth/me"))).rejects.toBeInstanceOf(ApiError);
    expect(ended).toHaveBeenCalledOnce();
    expect(getRefreshToken()).toBeNull();
    unsubscribe();
  });

  it("does not try to refresh after a failed login", async () => {
    fetchMock.mockResolvedValueOnce(json(401, { error: { code: "INVALID_CREDENTIALS", message: "Invalid email or password." } }));
    await expect(unwrap(api.POST("/api/v1/auth/login", { body: { email: "a@b.c", password: "x" } }))).rejects.toMatchObject({
      code: "INVALID_CREDENTIALS",
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
