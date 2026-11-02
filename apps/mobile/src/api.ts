import AsyncStorage from "@react-native-async-storage/async-storage";
import { Platform } from "react-native";
import { buildDemoMeal } from "./demoData";
import { demoScenarioFor } from "./demoScenarios";
import { inferImageMimeAndName } from "./mime";
import { t } from "./strings";
import { MealCorrection, MealLog, PendingCapture, UnverifiedNutritionEstimate } from "./types";

const defaultLocalApiUrl = Platform.OS === "android" ? "http://10.0.2.2:3000" : "http://localhost:3000";
export const apiBaseUrl = (process.env.EXPO_PUBLIC_API_URL || defaultLocalApiUrl).replace(/\/$/, "");
const demoMode = process.env.EXPO_PUBLIC_DEMO_MODE !== "false";
const fixtureSampleId = process.env.EXPO_PUBLIC_FIXTURE_SAMPLE_ID;

export const isDemoMode = demoMode;

export class MealApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "MealApiError";
    this.status = status;
  }
}

export type SubmitOptions = {
  demoRetry?: boolean;
};

export async function submitMeal(capture: PendingCapture, options: SubmitOptions = {}): Promise<MealLog> {
  if (demoMode) {
    await new Promise((resolve) => setTimeout(resolve, 850));
    if (demoScenarioFor(capture.text) === "error" && !options.demoRetry) {
      throw new Error(t("demoProviderError"));
    }
    return buildDemoMeal(options.demoRetry ? "pilav" : capture.text, capture.idempotencyKey);
  }

  if (!apiBaseUrl) {
    throw new Error(t("apiUrlMissing"));
  }

  const response = capture.photo
    ? await submitPhoto(capture)
    : await submitText(capture);

  if (!response.ok) {
    const rawBody = await response.text();
    let detail = rawBody;
    try {
      const parsed = JSON.parse(rawBody);
      if (parsed && typeof parsed.detail === "string") {
        detail = parsed.detail;
      }
    } catch {
      // not JSON
    }

    let message = detail;
    if (response.status === 503) {
      message = t("providerUnavailable");
    } else if (response.status === 429) {
      message = t("rateLimitExceeded");
    } else if (response.status === 415) {
      message = t("unsupportedMediaType");
    } else if (response.status === 413) {
      message = t("payloadTooLarge");
    } else if (!message || message.trim() === "") {
      message = `${t("uploadFailed")} (${response.status})`;
    }
    throw new MealApiError(response.status, message);
  }
  return response.json() as Promise<MealLog>;
}

const CLIENT_USER_ID_KEY = "@mealog/client-user-id";
let clientUserIdPromise: Promise<string> | null = null;
let resolvedClientUserId: string | null = null;

export async function getClientUserId(): Promise<string> {
  if (resolvedClientUserId) return resolvedClientUserId;
  if (!clientUserIdPromise) {
    clientUserIdPromise = (async () => {
      try {
        const saved = await AsyncStorage.getItem(CLIENT_USER_ID_KEY);
        if (saved) {
          resolvedClientUserId = saved;
          return saved;
        }
      } catch {
        // Fallback if storage fails
      }
      const newId = `client-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
      resolvedClientUserId = newId;
      try {
        await AsyncStorage.setItem(CLIENT_USER_ID_KEY, newId);
      } catch {
        // Ignore storage write error
      }
      return newId;
    })();
  }
  return clientUserIdPromise;
}

export function getSyncClientUserId(): string {
  return resolvedClientUserId || "demo-user";
}

/** What the catalogue says a typed food name is — or that it does not know. */
export type FoodResolution = {
  action: "resolved" | "abstain";
  query: string;
  locale: string;
  food_id: string;
  name: string | null;
  candidates: { food_id: string; name: string; score: number }[];
  confidence: number;
  grams: number;
  grams_p10: number;
  grams_p90: number;
  portion_source: string;
  portion_provenance: string;
  nutrients: { kcal: number; protein_g: number; carb_g: number; fat_g: number };
  source_database: string | null;
};

/**
 * Ask the catalogue what a typed name is. The client has no nutrition table of
 * its own (D1): this is the only way a typed food becomes a resolved item, and
 * an `abstain` is a real answer the caller must show as such.
 *
 * Demo mode answers from the bundled demo pack, because there is no server to
 * ask. That data is fixture-shaped and labelled as demo, never as catalogue.
 */
export async function resolveFoodName(text: string, locale = "tr"): Promise<FoodResolution> {
  if (!text.trim()) {
    throw new Error("Bir yemek adı yazın.");
  }
  if (demoMode) {
    const { resolveDemoFood } = await import("./demoResolve");
    return resolveDemoFood(text);
  }
  const userId = await getClientUserId();
  const response = await fetch(`${apiBaseUrl}/v1/foods/resolve`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-User-Id": userId,
    },
    body: JSON.stringify({ text, locale }),
  });
  if (!response.ok) {
    const message = response.status === 503
      ? "Bu dilin katalogu bu kurulumda yüklü değil."
      : response.status === 422
      ? "Bu yemek adı katalogda aranamadı."
      : `Katalog sorgulanamadı (${response.status}).`;
    throw new MealApiError(response.status, message);
  }
  return response.json() as Promise<FoodResolution>;
}

export async function correctMeal(meal: MealLog, corrections: MealCorrection[]): Promise<MealLog> {
  if (demoMode) {
    throw new Error(t("correctionNeedsServer"));
  }

  const userId = await getClientUserId();
  const response = await fetch(`${apiBaseUrl}/v1/meals/correct`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-User-Id": userId,
    },
    body: JSON.stringify({ meal, corrections }),
  });
  if (!response.ok) {
    const detail = await response.text();
    const message = response.status === 503
      ? t("providerUnavailable")
      : detail || `${t("correctionFailed")} (${response.status})`;
    throw new MealApiError(response.status, message);
  }
  return response.json() as Promise<MealLog>;
}

export type NutritionEstimateInput = { dish_name: string; quantity: number | null };

export async function estimateNutritionBatch(
  items: NutritionEstimateInput[],
  idempotencyKey: string,
): Promise<UnverifiedNutritionEstimate[]> {
  if (demoMode) {
    throw new Error("AI tahmini yalnızca canlı sağlayıcı modunda kullanılabilir.");
  }
  if (items.length < 1 || items.length > 20) {
    throw new Error("Tek öğünde en fazla 20 AI tahmini hazırlanabilir.");
  }
  const userId = await getClientUserId();
  const response = await fetch(`${apiBaseUrl}/v1/meals/estimate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-User-Id": userId,
      "X-Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify({ items }),
  });
  if (!response.ok) {
    const message = response.status === 503
      ? "AI tahmini şu anda alınamadı. Daha sonra yeniden deneyin."
      : response.status === 429
      ? "AI tahmini kotası doldu. Bir süre sonra yeniden deneyin; doğrulanmamış sayı üretilmedi."
      : `AI tahmini alınamadı (${response.status}).`;
    throw new MealApiError(response.status, message);
  }
  const payload = await response.json() as { estimates: UnverifiedNutritionEstimate[] };
  if (!Array.isArray(payload.estimates) || payload.estimates.length !== items.length) {
    throw new Error("AI tahmini eksik döndü. Lütfen yeniden deneyin.");
  }
  return payload.estimates;
}

async function submitText(capture: PendingCapture): Promise<Response> {
  const userId = await getClientUserId();
  return fetch(`${apiBaseUrl}/v1/meals`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-User-Id": userId,
    },
    body: JSON.stringify({
      idempotency_key: capture.idempotencyKey,
      locale: "tr",
      config: "V3",
      text: capture.text,
      ...(fixtureSampleId ? { sample_id: fixtureSampleId } : {}),
    }),
  });
}

async function submitPhoto(capture: PendingCapture): Promise<Response> {
  const userId = await getClientUserId();
  const form = new FormData();
  form.append("idempotency_key", capture.idempotencyKey);
  form.append("locale", "tr");
  form.append("config", "V3");
  const { mimeType, fileName } = inferImageMimeAndName(capture.photo?.uri, capture.photo?.mimeType);
  form.append("image", {
    uri: capture.photo?.uri,
    type: mimeType,
    name: fileName,
  } as unknown as Blob);

  return fetch(`${apiBaseUrl}/v1/meals`, {
    method: "POST",
    headers: {
      "X-User-Id": userId,
    },
    body: form,
  });
}
