import Slider from "@react-native-community/slider";
import { Ionicons } from "@expo/vector-icons";
import React, { useEffect, useState } from "react";
import { Alert, Image, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";

import { Candidate, CaptureMedium, ItemClarification, MealAction, MealLog, UnverifiedNutritionEstimate } from "../src/types";
import { formatLocalizedProvenance, formatLocalizedUnit, StringKey, t } from "../src/strings";
import { computedValuesNeedServerRefresh, countAnswerPending, getEffectiveQuantity, selectableCandidates, shouldShowCandidateEditor } from "../src/reviewState";
import { nutritionPresentationForItem } from "../src/nutritionPresentation";
import { sendTelemetryEvent, telemetryEventTypeForEdits } from "../src/telemetry";
import { apiBaseUrl, estimateNutritionBatch, getClientUserId, isDemoMode } from "../src/api";
import { AuditRow } from "../components/AuditRow";
import { Header } from "../components/Header";
import { actionLabel, actionTone } from "../components/meal";
import { colors } from "../components/theme";

export function getFoodEmoji(nameOrId: string): string {
  const s = (nameOrId || "").toLowerCase();
  if (s.includes("yumurta") || s.includes("egg") || s.includes("omlet") || s.includes("menemen")) return "🍳";
  if (s.includes("köfte") || s.includes("kofte") || s.includes("dana") || s.includes("kavurma") || s.includes("biftek") || s.includes("antrikot") || s.includes("döner") || s.includes("kebap") || s.includes("kırmızı et")) return "🥩";
  if (s.includes("pilav") || s.includes("pirinç") || s.includes("pirinc") || s.includes("bulgur")) return "🍚";
  if (s.includes("ekmek") || s.includes("pide") || s.includes("dilim")) return "🍞";
  if (s.includes("simit") || s.includes("poğaça") || s.includes("gevrek")) return "🥨";
  if (s.includes("salata") || s.includes("marul") || s.includes("yeşillik")) return "🥗";
  if (s.includes("çorba") || s.includes("corba") || s.includes("mercimek") || s.includes("ezogelin") || s.includes("tarhana")) return "🥣";
  if (s.includes("fasulye") || s.includes("nohut") || s.includes("güveç") || s.includes("türlü")) return "🥘";
  if (s.includes("lahmacun") || s.includes("pizza") || s.includes("börek")) return "🍕";
  if (s.includes("makarna") || s.includes("mantı") || s.includes("manti")) return "🍝";
  if (s.includes("ayran") || s.includes("yoğurt") || s.includes("yogurt") || s.includes("cacık")) return "🥛";
  if (s.includes("süt") || s.includes("sut")) return "🥛";
  if (s.includes("çay") || s.includes("cay") || s.includes("kahve")) return "☕";
  if (s.includes("meyve_suyu") || s.includes("kola") || s.includes("meşrubat")) return "🧃";
  if (s.includes("hamsi") || s.includes("balık") || s.includes("somon") || s.includes("ton")) return "🐟";
  if (s.includes("peynir") || s.includes("kaşar") || s.includes("kasar") || s.includes("beyaz peynir")) return "🧀";
  if (s.includes("zeytin")) return "🫒";
  if (s.includes("elma")) return "🍎";
  if (s.includes("muz")) return "🍌";
  if (s.includes("portakal")) return "🍊";
  if (s.includes("salatalık") || s.includes("salatalik") || s.includes("hıyar") || s.includes("turşu") || s.includes("tursu")) return "🥒";
  if (s.includes("patates") || s.includes("kızartma")) return "🍟";
  if (s.includes("baklava") || s.includes("tatlı") || s.includes("kadayıf") || s.includes("sütlaç") || s.includes("helva")) return "🍮";
  if (s.includes("fındık") || s.includes("fıstık") || s.includes("ceviz") || s.includes("badem")) return "🥜";
  if (s.includes("bal") || s.includes("reçel")) return "🍯";
  if (s.includes("burger") || s.includes("hamburger")) return "🍔";
  return "🍽️";
}

// This screen holds no nutrition values of its own (D1). A typed food name is
// resolved by the server at POST /v1/foods/resolve, and the item it returns is
// displayed as-is. Which food a name means is the catalogue's call; the client
// only chooses a portion and picks between candidates it was given.

type PortionSliderProps = {
  minimumValue: number;
  maximumValue: number;
  value: number;
  minimumTrackTintColor: string;
  maximumTrackTintColor: string;
  thumbTintColor: string;
  onValueChange: (value: number) => void;
  accessibilityLabel: string;
};

const PortionSlider = Slider as unknown as React.ComponentType<PortionSliderProps>;

function quantityLabel(item: MealLog["items"][number], quantity = item.quantity, unit = item.unit) {
  if (quantity === null || quantity === undefined) {
    return t("quantityUnknown");
  }
  const localizedUnit = formatLocalizedUnit(unit);
  return t("quantityValue", { quantity: String(quantity), unit: localizedUnit ? ` ${localizedUnit}` : "" });
}

function resolveSelectedName(item: MealLog["items"][number], selected: string, customName?: string) {
  if (selected === "USER_CUSTOM") return customName || item.query || "Özel Yemek";
  const cand = item.candidates.find((candidate) => candidate.food_id === selected);
  if (cand) return cand.name;
  // A food_id the server sent without a matching candidate still has no local
  // name to borrow: show the user's own words rather than a guess.
  return item.query || selected;
}

function captureMediumCopy(medium: CaptureMedium): StringKey {
  if (medium === "screen") return "captureMediumScreen";
  if (medium === "printed") return "captureMediumPrinted";
  if (medium === "toy_or_model") return "captureMediumToy";
  return "captureMediumUnclear";
}

export interface SmartBannerDetails {
  title: string;
  text: string;
  actionType?: MealAction;
  unmatchedNames?: string[];
  pendingCountNames?: string[];
  totalPendingCount?: number;
}

function getSmartActionBannerDetails(
  meal: MealLog,
  selectedCandidates: Record<number, string>,
  quantityEdits: Record<number, number | null>,
): SmartBannerDetails {
  if (meal.degraded) {
    return {
      title: t("degradedTitle"),
      text: t("degradedCopy"),
    };
  }

  const unmatchedItems = meal.items.filter((item, i) => {
    const sel = selectedCandidates[i] ?? item.food_id;
    return sel === "ABSTAIN";
  });

  const pendingCountItems = meal.items.filter((item, i) => {
    if (meal.items.length === 1 && item.confidence >= 0.85) return false;
    const isUnmatched = (selectedCandidates[i] ?? item.food_id) === "ABSTAIN";
    if (isUnmatched) return false;
    return item.clarification?.kind === "count" && !Object.prototype.hasOwnProperty.call(quantityEdits, i);
  });

  const unmatchedNames = unmatchedItems.map((u) => u.query);
  const pendingCountNames = pendingCountItems.map((item) => {
    const idx = meal.items.indexOf(item);
    const sel = selectedCandidates[idx] ?? item.food_id;
    return resolveSelectedName(item, sel);
  });
  const totalPendingCount = unmatchedItems.length + pendingCountItems.length;

  // When both unmatched items AND pending count clarifications exist:
  if (unmatchedItems.length > 0 && pendingCountItems.length > 0) {
    return {
      title: `${totalPendingCount} Öğede Seçim Bekleniyor`,
      text: `Tabaktaki ${unmatchedNames.join(", ")} için yemek eşleşmesi; ${pendingCountNames.join(", ")} için porsiyon/adet seçimi bekleniyor.`,
      unmatchedNames,
      pendingCountNames,
      totalPendingCount,
      actionType: "ask",
    };
  }

  // When only unmatched items exist:
  if (unmatchedItems.length > 0) {
    return {
      title: unmatchedItems.length > 1 ? `${unmatchedItems.length} Öğede Güvenli Eşleşme Yok` : "Güvenli Eşleşme Yok",
      text: `Tabaktaki ${unmatchedNames.join(", ")} güvenli şekilde kataloğa bağlanamadı. Yanlış bir adayı seçmek zorunda değilsiniz; yemeği değiştirin, kaldırın veya doğrulanmamış AI tahminini inceleyin.`,
      unmatchedNames,
      totalPendingCount: unmatchedItems.length,
      actionType: "ask",
    };
  }

  // When only count clarifications exist:
  if (pendingCountItems.length > 0) {
    return {
      title: pendingCountItems.length > 1 ? `${pendingCountItems.length} Öğede Porsiyon Belirsizliği` : "Porsiyon / Miktar Belirsizliği",
      text: `Tabaktaki ${pendingCountNames.join(", ")} için lütfen porsiyon miktarınızı seçin.`,
      pendingCountNames,
      totalPendingCount: pendingCountItems.length,
      actionType: "ask",
    };
  }

  const unverifiedEstimateItems = meal.items.filter((item) => (
    item.portion_provenance === "llm_unverified_estimate"
    && item.nutrition_estimate?.provenance === "llm_unverified_estimate"
  ));

  if (unverifiedEstimateItems.length > 0) {
    const estimateNames = unverifiedEstimateItems.map((item) => item.query).join(", ");
    return {
      title: unverifiedEstimateItems.length === meal.items.length
        ? "Doğrulanmamış AI Tahmini"
        : "Doğrulanmamış Tahmin İçeren Öğün",
      text: `${estimateNames} için değerler Gemini genel bilgisinden geldi. Katalog veya laboratuvar verisi değildir; aralıkları ve varsayımları inceleyin.`,
      actionType: "review",
    };
  }

  const customItems = meal.items.filter((item, i) => {
    const sel = selectedCandidates[i] ?? item.food_id;
    return sel === "USER_CUSTOM";
  });

  if (customItems.length > 0) {
    const isEntireMealCustom = customItems.length === meal.items.length;
    if (isEntireMealCustom) {
      return {
        title: "Manuel Öğün Girişi",
        text: "Bu öğünün besin değerleri kullanıcı tarafından girildi. Kaydetmeden önce değerleri inceleyin.",
        actionType: "review",
      };
    } else {
      const customNames = customItems.map((c) => c.query).join(", ");
      return {
        title: "Manuel Değer İçeren Öğün",
        text: `Katalog yemekleri resmi veriyle eşleşti; ${customNames} öğesi kullanıcı tarafından girildi.`,
        actionType: "review",
      };
    }
  }

  const rangeItem = meal.items.find((item) => item.grams_p90 > item.grams_p10);
  if (rangeItem) {
    return {
      title: "Porsiyonu Gözden Geçirin",
      text: "Yemekler katalogla eşleşti; porsiyon miktarını dilerseniz butonlarla veya gram kutusuyla özelleştirebilirsiniz.",
      actionType: "review",
    };
  }

  return {
    title: "Tüm Öğeler Doğrulandı",
    text: "Tüm seçimler ve eşleşmeler tamamlandı. Tabağınızı gününüze kaydedebilirsiniz.",
    actionType: "auto_accept",
  };
}

export type ReviewScreenProps = {
  meal: MealLog;
  imageUri?: string | null;
  expandedItem: number | null;
  setExpandedItem: (value: number | null) => void;
  portionEdits: Record<number, number>;
  setPortionEdits: React.Dispatch<React.SetStateAction<Record<number, number>>>;
  quantityEdits: Record<number, number | null>;
  setQuantityEdits: React.Dispatch<React.SetStateAction<Record<number, number | null>>>;
  selectedCandidates: Record<number, string>;
  onChooseCandidate: (index: number, candidate: Candidate) => void;
  onRemoveItem?: (index: number) => void;
  /** Resolves `true` when the food was added; `false` when the catalogue did not know it. */
  onAddItem?: (foodName: string, calories?: number) => Promise<boolean> | boolean | void;
  onAcceptEstimate?: (index: number, estimate: UnverifiedNutritionEstimate) => void;
  onSave: () => void;
  isSaved?: boolean;
  saving?: boolean;
  onBack: () => void;
  scrollY?: number;
  testFold?: "top" | "details" | "actions" | "bottom";
};

export function ReviewScreen({
  meal,
  imageUri,
  expandedItem,
  setExpandedItem,
  portionEdits,
  setPortionEdits,
  quantityEdits,
  setQuantityEdits,
  selectedCandidates,
  onChooseCandidate,
  onRemoveItem,
  onAddItem,
  onAcceptEstimate,
  onSave,
  isSaved = false,
  saving = false,
  onBack,
  scrollY = 0,
  testFold,
}: ReviewScreenProps) {
  const displayAction = meal.degraded ? "review" : meal.action;
  const tone = actionTone(displayAction);
  const flaggedMedium = meal.items.find((item) => (item.capture_medium ?? "real_plate") !== "real_plate")?.capture_medium ?? null;

  // Accordion state: auto-open items that require user attention (ABSTAIN or pending count clarification on complex meals)
  const [openItems, setOpenItems] = useState<Record<number, boolean>>(() => {
    const initial: Record<number, boolean> = {};
    meal.items.forEach((item, idx) => {
      const isAbstain = item.food_id === "ABSTAIN";
      const isSingleConfident = meal.items.length === 1 && item.confidence >= 0.85;
      const hasCount = item.clarification?.kind === "count" && !isSingleConfident;
      if (isAbstain || hasCount) {
        initial[idx] = true;
      }
    });
    return initial;
  });

  function toggleItem(index: number) {
    setOpenItems((prev) => ({ ...prev, [index]: !prev[index] }));
  }

  // Toggled sub-controls (portion editor & candidate editor)
  const [showPortionEdit, setShowPortionEdit] = useState<Record<number, boolean>>(() => {
    const initial: Record<number, boolean> = {};
    meal.items.forEach((item, idx) => {
      const isSingleConfident = meal.items.length === 1 && item.confidence >= 0.85;
      if (item.clarification?.kind === "count" && !isSingleConfident) {
        initial[idx] = true;
      }
    });
    return initial;
  });
  const [showCandidateEdit, setShowCandidateEdit] = useState<Record<number, boolean>>({});

  // Custom food details per item index
  const [customFoodDetails, setCustomFoodDetails] = useState<Record<number, { name: string; kcal: number; grams: number }>>({});

  // "+ Başka..." Custom search/manual entry state
  const [customSearchIndex, setCustomSearchIndex] = useState<number | null>(null);
  const [customFoodQuery, setCustomFoodQuery] = useState("");
  const [customNotFound, setCustomNotFound] = useState(false);
  const [customCaloriesInput, setCustomCaloriesInput] = useState("");

  // + Tabağa Öğe Ekle state
  const [showAddPlateItem, setShowAddPlateItem] = useState(false);
  const [newPlateItemQuery, setNewPlateItemQuery] = useState("");
  const [newPlateItemKcal, setNewPlateItemKcal] = useState("");
  const [newPlateItemNotFound, setNewPlateItemNotFound] = useState(false);
  const [nutritionEstimates, setNutritionEstimates] = useState<Record<number, UnverifiedNutritionEstimate>>({});
  const [estimateLoading, setEstimateLoading] = useState<Record<number, boolean>>({});
  const [estimateErrors, setEstimateErrors] = useState<Record<number, string>>({});

  // Audit details state: strictly collapsed by default
  const [openAuditItems, setOpenAuditItems] = useState<Record<number, boolean>>({});
  function toggleAudit(index: number) {
    setOpenAuditItems((prev) => ({ ...prev, [index]: !prev[index] }));
  }

  const hasUnansweredCountClarification = meal.items.some((item, index) => {
    const hasQuantityEdit = Object.prototype.hasOwnProperty.call(quantityEdits, index);
    return countAnswerPending(item, hasQuantityEdit);
  });
  const needsPortionConfirmation = hasUnansweredCountClarification;

  const hasUnresolvedAbstain = meal.items.some((item, index) => {
    const selected = selectedCandidates[index] ?? item.food_id;
    return selected === "ABSTAIN";
  });

  const pendingCountItems = meal.items.filter((item, i) => item.clarification?.kind === "count" && !Object.prototype.hasOwnProperty.call(quantityEdits, i));
  const hasPendingQuestions = hasUnresolvedAbstain || pendingCountItems.length > 0;

  const isSaveDisabled = Boolean(saving || hasUnresolvedAbstain);
  const unresolvedChoiceHint = "Güvenli eşleşme bulunmayan öğeler var; yemeği değiştirin, kaldırın veya doğrulanmamış AI tahminini inceleyin.";
  const footerHint = hasUnresolvedAbstain && pendingCountItems.length > 0
    ? "Çözülmemiş yemek eşleşmeleri ve porsiyon seçimleri var; kaydetmeden önce aşağıdaki listeden tamamlayın."
    : hasUnresolvedAbstain
    ? unresolvedChoiceHint
    : null;

  const bannerDetails = getSmartActionBannerDetails(meal, selectedCandidates, quantityEdits);

  function handleSave() {
    if (saving) return;
    if (hasUnresolvedAbstain) {
      Alert.alert("Güvenli eşleşme yok", unresolvedChoiceHint);
      return;
    }
    meal.items.forEach((item, index) => {
      if (item.clarification?.kind === "count" && !Object.prototype.hasOwnProperty.call(quantityEdits, index)) {
        setQuantityEdits((current) => ({ ...current, [index]: 1 }));
      }
    });

    const hasCandidateEdit = Object.keys(selectedCandidates).length > 0;
    const hasPortionOrQuantityEdit = Object.keys(portionEdits).length > 0 || Object.keys(quantityEdits).length > 0;
    const telemetryPayload = {
      idempotency_key: meal.idempotency_key,
      locale: meal.locale ?? "tr",
      event_type: telemetryEventTypeForEdits(hasCandidateEdit, hasPortionOrQuantityEdit),
      input_mode: meal.items[0]?.capture_medium === "real_plate" ? "image" : "text",
      items: meal.items.map((it, idx) => ({
        original_query: it.query,
        predicted_food_id: it.food_id,
        selected_food_id: selectedCandidates[idx] ?? it.food_id,
        predicted_grams: it.grams,
        selected_grams: portionEdits[idx] ?? it.grams,
        delta_reason: hasCandidateEdit || hasPortionOrQuantityEdit
          ? "user_mobile_review_edit"
          : "user_accepted_without_edit",
      })),
      total_kcal_before: meal.totals?.kcal,
      total_kcal_after: liveTotalKcal,
    } as const;
    if (!isDemoMode) {
      void getClientUserId().then((userId) => sendTelemetryEvent(apiBaseUrl, userId, telemetryPayload));
    }

    onSave();
  }

  function setPortionQuick(index: number, grams: number) {
    setPortionEdits((current) => ({ ...current, [index]: grams }));
  }

  function handleSearchCustomFood(index: number) {
    const trimmed = customFoodQuery.trim();
    if (!trimmed) return;

    const existing = meal.items[index]?.candidates.find(
      (c) => c.name.toLowerCase().includes(trimmed.toLowerCase()) || trimmed.toLowerCase().includes(c.name.toLowerCase())
    );

    if (existing) {
      onChooseCandidate(index, existing);
      setCustomSearchIndex(null);
      setCustomFoodQuery("");
      setCustomNotFound(false);
      Alert.alert("Katalog Eşleşti", `"${existing.name}" katalogdan başarıyla eşleştirildi.`);
    } else {
      setCustomNotFound(true);
    }
  }

  function handleSaveCustomManualDish(index: number) {
    const name = customFoodQuery.trim() || "Özel Yemek";
    const kcal = parseInt(customCaloriesInput.replace(/[^0-9]/g, ""), 10);
    if (!Number.isFinite(kcal) || kcal <= 0 || kcal > 5000) {
      Alert.alert("Geçersiz kalori", "1–5000 arasında bir kalori değeri girin.");
      return;
    }

    setCustomFoodDetails((prev) => ({
      ...prev,
      [index]: { name, kcal, grams: 0 },
    }));

    const customCandidate: Candidate = {
      food_id: "USER_CUSTOM",
      name: name,
      score: 1.0,
    };

    onChooseCandidate(index, customCandidate);
    setCustomSearchIndex(null);
    setCustomFoodQuery("");
    setCustomNotFound(false);
    Alert.alert("Özel Yemek Eklendi", `"${name}" (${kcal} kcal) manuel kullanıcı girişi olarak tabağa eklendi.`);
  }

  async function requestNutritionEstimates(indexes: number[]) {
    if (indexes.length === 0) return;
    setEstimateLoading((current) => ({
      ...current,
      ...Object.fromEntries(indexes.map((index) => [index, true])),
    }));
    setEstimateErrors((current) => ({
      ...current,
      ...Object.fromEntries(indexes.map((index) => [index, ""])),
    }));
    try {
      const estimates = await estimateNutritionBatch(
        indexes.map((index) => ({
          dish_name: meal.items[index]?.query || "Yemek",
          quantity: meal.items[index]?.quantity ?? null,
        })),
        `${meal.idempotency_key}:nutrition:${indexes.join("-")}`,
      );
      setNutritionEstimates((current) => ({
        ...current,
        ...Object.fromEntries(indexes.map((index, offset) => [index, estimates[offset]])),
      }));
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "AI tahmini alınamadı.";
      setEstimateErrors((current) => ({
        ...current,
        ...Object.fromEntries(indexes.map((index) => [index, message])),
      }));
    } finally {
      setEstimateLoading((current) => ({
        ...current,
        ...Object.fromEntries(indexes.map((index) => [index, false])),
      }));
    }
  }

  useEffect(() => {
    if (isDemoMode) return;
    const allUnresolvedIndexes = meal.items
      .map((item, index) => ({ item, index }))
      .filter(({ item, index }) => (selectedCandidates[index] ?? item.food_id) === "ABSTAIN")
      .map(({ index }) => index);
    const unresolvedIndexes = allUnresolvedIndexes.slice(0, 20);
    const overflowIndexes = allUnresolvedIndexes.slice(20);
    if (overflowIndexes.length > 0) {
      setEstimateErrors((current) => ({
        ...current,
        ...Object.fromEntries(overflowIndexes.map((index) => [index, "Bu öğünde 20 AI tahmini sınırına ulaşıldı."])),
      }));
    }
    void requestNutritionEstimates(unresolvedIndexes);
    // One automatic batch per meal. Candidate edits must not trigger new provider calls.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meal.idempotency_key]);

  // Calculate live total macros across all items (including newly resolved candidates)
  let liveTotalKcal = 0;
  let liveTotalProtein = 0;
  let liveTotalCarb = 0;
  let liveTotalFat = 0;

  meal.items.forEach((item, index) => {
    const selected = selectedCandidates[index] ?? item.food_id;
    if (selected === "ABSTAIN") return;

    const hasQuantityEdit = Object.prototype.hasOwnProperty.call(quantityEdits, index);
    const hasPortionEdit = Object.prototype.hasOwnProperty.call(portionEdits, index);
    const serverQty = (typeof item.quantity === "number" && item.quantity > 0) ? item.quantity : 1;
    const quantity = getEffectiveQuantity(item, hasQuantityEdit, quantityEdits[index]);
    const currentQty = (typeof quantity === "number" && quantity > 0) ? quantity : 1;
    const quantityRatio = hasQuantityEdit ? (currentQty / serverQty) : 1;

    // Portion edits rescale a value the server computed. When the server sent
    // no mass there is nothing to rescale, so the macros stay at zero and the
    // item is shown as uncaloried — never as a client-side estimate.
    const customInfo = customFoodDetails[index];

    const baseGrams = (item.grams > 0) ? item.grams : (customInfo?.grams ?? 0);
    const baseKcal = item.nutrients.kcal > 0 ? item.nutrients.kcal : customInfo?.kcal ?? 0;
    const baseProtein = item.nutrients.protein_g > 0 ? item.nutrients.protein_g : 0;
    const baseCarb = item.nutrients.carb_g > 0 ? item.nutrients.carb_g : 0;
    const baseFat = item.nutrients.fat_g > 0 ? item.nutrients.fat_g : 0;

    const effectiveGrams = hasPortionEdit
      ? portionEdits[index]
      : hasQuantityEdit
      ? Math.round(baseGrams * quantityRatio)
      : Math.round(baseGrams);
    const gramRatio = (baseGrams > 0 && effectiveGrams > 0) ? (effectiveGrams / baseGrams) : 1;

    liveTotalKcal += Math.round(baseKcal * gramRatio);
    liveTotalProtein += Math.round(baseProtein * gramRatio);
    liveTotalCarb += Math.round(baseCarb * gramRatio);
    liveTotalFat += Math.round(baseFat * gramRatio);
  });

  const isBottomFold = testFold === "bottom";
  const showTopHeader = !testFold || testFold === "top";

  return (
    <View style={styles.screen}>
      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.content}
        contentOffset={{ x: 0, y: testFold === "bottom" ? 350 : 0 }}
      >
        {showTopHeader ? (
          <>
            <Header eyebrow={t("reviewEyebrow")} title={isSaved ? t("savedReviewTitle") : t("reviewTitle")} subtitle={isSaved ? t("savedReviewSubtitle") : t("reviewSubtitle")} />

            {imageUri ? (
              <View style={styles.imageContainer}>
                <Image source={{ uri: imageUri }} style={styles.previewBackdrop} resizeMode="cover" blurRadius={14} />
                <Image source={{ uri: imageUri }} style={styles.previewImage} resizeMode="contain" />
                <View style={styles.imageBadge}>
                  <Ionicons name="image-outline" size={13} color={colors.white} />
                  <Text style={styles.imageBadgeText}>{t("mealPhotoBadge")}</Text>
                </View>
              </View>
            ) : null}

            {meal.degraded ? (
              <View style={styles.degradedBanner}>
                <Ionicons name="warning-outline" size={19} color="#8D641C" />
                <View style={styles.degradedCopy}>
                  <Text style={styles.degradedTitle}>{t("degradedTitle")}</Text>
                  <Text style={styles.degradedText}>{t("degradedCopy")}</Text>
                </View>
              </View>
            ) : null}
            {flaggedMedium ? (
              <View style={styles.captureMediumBanner}>
                <Ionicons name="image-outline" size={19} color="#8D641C" />
                <View style={styles.degradedCopy}>
                  <Text style={styles.degradedTitle}>{t("captureMedium")}</Text>
                  <Text style={styles.degradedText}>{t(captureMediumCopy(flaggedMedium))}</Text>
                </View>
              </View>
            ) : null}

            {/* Smart Modern Action Callout Banner */}
            {(() => {
              const currentAction = bannerDetails.actionType ?? (hasPendingQuestions ? "ask" : "auto_accept");
              const isAsk = currentAction === "ask";
              const isAutoAccept = currentAction === "auto_accept";
              const isReview = currentAction === "review";

              return (
                <View
                  style={[
                    styles.modernBannerCard,
                    isAsk && styles.modernBannerAsk,
                    isAutoAccept && styles.modernBannerAccept,
                    isReview && styles.modernBannerReview,
                  ]}
                >
                  <View style={styles.modernBannerTopRow}>
                    <View style={styles.modernBannerBadgeWrap}>
                      <View
                        style={[
                          styles.modernBannerIconCircle,
                          isAsk && styles.modernIconCircleAsk,
                          isAutoAccept && styles.modernIconCircleAccept,
                          isReview && styles.modernIconCircleReview,
                        ]}
                      >
                        <Ionicons
                          name={isAutoAccept ? "checkmark-circle" : isAsk ? "sparkles" : "options-outline"}
                          size={15}
                          color={isAutoAccept ? colors.moss : isAsk ? "#8D641C" : colors.ink}
                        />
                      </View>
                      <Text
                        style={[
                          styles.modernBannerCategoryTag,
                          isAsk && styles.categoryTagAsk,
                          isAutoAccept && styles.categoryTagAccept,
                        ]}
                      >
                        {isAutoAccept
                          ? "GÜVENLE DOĞRULANDI"
                          : isAsk
                          ? "KONTROL & SEÇİM"
                          : "PORSİYON GÖZDEN GEÇİRME"}
                      </Text>
                    </View>

                    {bannerDetails.totalPendingCount && bannerDetails.totalPendingCount > 0 ? (
                      <View style={styles.modernPendingPill}>
                        <Text style={styles.modernPendingPillText}>
                          {bannerDetails.totalPendingCount} İşlem Bekliyor
                        </Text>
                      </View>
                    ) : null}
                  </View>

                  <Text style={styles.modernBannerMainTitle}>{bannerDetails.title}</Text>

                  {/* Structured visual item tags */}
                  {((bannerDetails.unmatchedNames && bannerDetails.unmatchedNames.length > 0) ||
                    (bannerDetails.pendingCountNames && bannerDetails.pendingCountNames.length > 0)) ? (
                    <View style={styles.modernPillsGroup}>
                      {bannerDetails.unmatchedNames && bannerDetails.unmatchedNames.length > 0 ? (
                        <View style={styles.modernPillCategoryRow}>
                          <Text style={styles.modernPillGroupLabel}>Belirsiz:</Text>
                          <View style={styles.modernItemTagsRow}>
                            {bannerDetails.unmatchedNames.map((name) => (
                              <View key={name} style={styles.modernUnmatchedTag}>
                                <Text style={styles.modernTagEmoji}>{getFoodEmoji(name)}</Text>
                                <Text style={styles.modernUnmatchedTagText}>{name}</Text>
                              </View>
                            ))}
                          </View>
                        </View>
                      ) : null}

                      {bannerDetails.pendingCountNames && bannerDetails.pendingCountNames.length > 0 ? (
                        <View style={styles.modernPillCategoryRow}>
                          <Text style={styles.modernPillGroupLabel}>Porsiyon:</Text>
                          <View style={styles.modernItemTagsRow}>
                            {bannerDetails.pendingCountNames.map((name) => (
                              <View key={name} style={styles.modernCountTag}>
                                <Text style={styles.modernTagEmoji}>{getFoodEmoji(name)}</Text>
                                <Text style={styles.modernCountTagText}>{name}</Text>
                              </View>
                            ))}
                          </View>
                        </View>
                      ) : null}
                    </View>
                  ) : (
                    <Text style={styles.modernBannerDescription}>{bannerDetails.text}</Text>
                  )}
                </View>
              );
            })()}

            {/* Bento Macro Summary Bar */}
            <View style={styles.bentoSummaryCard}>
              <View style={styles.bentoSummaryHeader}>
                <View style={styles.bentoKcalBadge}>
                  <Ionicons name="flame" size={18} color={colors.terracotta} />
                  <Text style={styles.bentoKcalValue}>{liveTotalKcal > 0 ? liveTotalKcal : meal.totals.kcal}</Text>
                  <Text style={styles.bentoKcalUnit}>kcal toplam</Text>
                </View>
                <View style={styles.bentoItemCountBadge}>
                  <Ionicons name="restaurant-outline" size={13} color={colors.moss} />
                  <Text style={styles.bentoItemCountText}>{meal.items.length} Öğe</Text>
                </View>
              </View>
              <View style={styles.bentoMacroRow}>
                <View style={styles.bentoMacroPill}>
                  <Text style={styles.bentoMacroLabel}>Protein</Text>
                  <Text style={styles.bentoMacroValue}>{liveTotalProtein > 0 ? liveTotalProtein : meal.totals.protein_g} g</Text>
                </View>
                <View style={styles.bentoMacroPill}>
                  <Text style={styles.bentoMacroLabel}>Karb</Text>
                  <Text style={styles.bentoMacroValue}>{liveTotalCarb > 0 ? liveTotalCarb : meal.totals.carb_g ?? 0} g</Text>
                </View>
                <View style={styles.bentoMacroPill}>
                  <Text style={styles.bentoMacroLabel}>Yağ</Text>
                  <Text style={styles.bentoMacroValue}>{liveTotalFat > 0 ? liveTotalFat : meal.totals.fat_g ?? 0} g</Text>
                </View>
              </View>
            </View>
          </>
        ) : null}

        {isBottomFold ? (
          <Header eyebrow="ÖĞÜN DETAYLARI & EŞLEŞMELER" title="Kalori, Porsiyon ve Adaylar" subtitle="Tabağın besin değerleri, porsiyon ayarı ve alternatif katalog adayları." />
        ) : null}

        <View style={styles.itemsSectionHeader}>
          <Text style={styles.itemsSectionTitle}>Tabaktaki Öğeler ({meal.items.length})</Text>
          <Text style={styles.itemsSectionSubtitle}>Detayları görmek veya porsiyonu ayarlamak için dokunun</Text>
        </View>

        {meal.items.map((item, index) => {
          const selected = selectedCandidates[index] ?? item.food_id;
          const isAbstain = selected === "ABSTAIN";
          const isUnverifiedEstimate = item.portion_provenance === "llm_unverified_estimate";

          const hasQuantityEdit = Object.prototype.hasOwnProperty.call(quantityEdits, index);
          const hasPortionEdit = Object.prototype.hasOwnProperty.call(portionEdits, index);
          const serverQty = (typeof item.quantity === "number" && item.quantity > 0) ? item.quantity : 1;
          const quantity = getEffectiveQuantity(item, hasQuantityEdit, quantityEdits[index]);
          const currentQty = (typeof quantity === "number" && quantity > 0) ? quantity : 1;
          const quantityRatio = hasQuantityEdit ? (currentQty / serverQty) : 1;

          const customInfo = customFoodDetails[index];

          const baseGrams = (item.grams > 0) ? item.grams : (customInfo?.grams ?? 0);
          const baseKcal = item.nutrients.kcal > 0 ? item.nutrients.kcal : customInfo?.kcal ?? 0;
          const baseProtein = item.nutrients.protein_g > 0 ? item.nutrients.protein_g : 0;
          const baseCarb = item.nutrients.carb_g > 0 ? item.nutrients.carb_g : 0;
          const baseFat = item.nutrients.fat_g > 0 ? item.nutrients.fat_g : 0;

          const effectiveGrams = hasPortionEdit
            ? portionEdits[index]
            : hasQuantityEdit
            ? Math.round(baseGrams * quantityRatio)
            : Math.round(baseGrams);

          const effectiveLow = item.grams_p10 > 0 ? Math.round(item.grams_p10 * quantityRatio) : Math.round(effectiveGrams * 0.75);
          const effectiveHigh = item.grams_p90 > 0 ? Math.round(item.grams_p90 * quantityRatio) : Math.round(effectiveGrams * 1.25);
          const grams = effectiveGrams;

          const clarification = item.clarification ?? null;
          const quantityUnit = clarification && clarification.kind === "count" ? clarification.unit ?? item.unit : item.unit;
          const hasRange = effectiveHigh > effectiveLow;
          const isCountAnswerPending = countAnswerPending(item, hasQuantityEdit);
          const isDeferred = computedValuesNeedServerRefresh(item, hasQuantityEdit, quantity);
          const nutritionPresentation = selected === "USER_CUSTOM" ? "manual" : isAbstain ? "pending" : "verified";
          const hasLocalNutritionEdit = Boolean(hasPortionEdit || hasQuantityEdit);
          const nutritionRecalculationPending = false;

          const displayedQuantity = isCountAnswerPending
            ? t("quantityPending")
            : quantityLabel(item, quantity, quantityUnit);

          const gramRatio = (baseGrams > 0 && grams > 0) ? (grams / baseGrams) : 1;
          const previewKcal = isAbstain ? 0 : Math.round(baseKcal * gramRatio);
          const previewProtein = isAbstain ? 0 : Math.round(baseProtein * gramRatio);
          const previewCarb = isAbstain ? 0 : Math.round(baseCarb * gramRatio);
          const previewFat = isAbstain ? 0 : Math.round(baseFat * gramRatio);

          const isExpanded = Boolean(openItems[index]);
          const isAuditExpanded = Boolean(openAuditItems[index]);
          const expandedItem = isAuditExpanded ? index : null;
          const isItemAuditExpanded = expandedItem === index;

          // Clean display name
          const displayName = isAbstain
            ? `${item.query || "Yemek"} (Güvenli Eşleşme Yok)`
            : selected === "USER_CUSTOM"
            ? `${resolveSelectedName(item, selected, customInfo?.name)} (Özel)`
            : resolveSelectedName(item, selected);

          const foodEmoji = getFoodEmoji(selected + " " + item.query + " " + displayName);

          // Portion & Candidates sub-panels:
          const shouldShowPortion = !isAbstain && Boolean(showPortionEdit[index]);
          const shouldShowCandidates = shouldShowCandidateEditor(
            isAbstain,
            Boolean(showCandidateEdit[index]),
            customSearchIndex === index,
          );
          const candidateChoices = selectableCandidates(isAbstain, item.candidates);

          return (
            <View key={`${item.query}-${index}`} style={[styles.itemCard, isExpanded && styles.itemCardExpanded]}>
              {/* Interactive Accordion Header with Food Emoji */}
              <Pressable
                style={styles.itemAccordionHeader}
                onPress={() => toggleItem(index)}
                accessibilityRole="button"
                accessibilityLabel={`${item.query} detayları`}
              >
                <View style={styles.itemEmojiWrap}>
                  <Text style={styles.itemEmojiText}>{foodEmoji}</Text>
                </View>
                <View style={styles.itemNameWrap}>
                  <Text style={styles.itemMatch} numberOfLines={1}>
                    {displayName}
                  </Text>
                  <View style={[styles.itemHeaderSubRow, styles.statusBadgesRow]}>
                    <Text style={styles.quantityText}>
                      {isAbstain
                        ? "Yanlış aday seçilmedi"
                        : !hasQuantityEdit && clarification?.kind === "count" && !(meal.items.length === 1 && item.confidence >= 0.85)
                        ? "Porsiyon Seçimi Bekleniyor"
                        : grams > 0
                        ? `${displayedQuantity} (${grams}g)`
                        : displayedQuantity}
                    </Text>
                    {isAbstain ? (
                      <View style={[styles.confidencePillMini, styles.confidenceLow]}>
                        <Text style={[styles.confidenceTextMini, styles.confidenceTextLow]}>
                          Karar Bekliyor
                        </Text>
                      </View>
                    ) : !hasQuantityEdit && clarification?.kind === "count" && !(meal.items.length === 1 && item.confidence >= 0.85) ? (
                      <View style={[styles.confidencePillMini, styles.confidenceMed]}>
                        <Text style={[styles.confidenceTextMini, styles.confidenceTextMed]}>
                          Seçim Bekleniyor
                        </Text>
                      </View>
                    ) : null}
                  </View>
                </View>
                <View style={styles.itemHeaderRight}>
                  <View style={styles.itemHeaderKcalChevronRow}>
                    <Text style={[styles.itemHeaderKcal, isAbstain && styles.itemHeaderKcalZero]}>
                      {isAbstain ? "— kcal" : `≈ ${previewKcal} kcal`}
                    </Text>
                    <View style={styles.chevronCircle}>
                      <Ionicons name={isExpanded ? "chevron-up" : "chevron-down"} size={16} color={colors.ink} />
                    </View>
                  </View>
                  {!isAbstain ? (
                    <>
                      <Text style={styles.itemHeaderMacrosMini}>
                        {previewProtein}g P · {previewCarb}g K · {previewFat}g Y
                      </Text>
                      {isUnverifiedEstimate ? <Text style={styles.unverifiedInlineTag}>AI tahmini · doğrulanmamış</Text> : null}
                    </>
                  ) : null}
                </View>
              </Pressable>

              {/* Expanded Details Body */}
              {isExpanded ? (
                <View style={styles.itemDetailsBody}>
                  {isAbstain ? (
                    <View style={styles.abstainCardNotice}>
                      <View style={styles.abstainNoticeLeft}>
                        <Ionicons name="help-circle-outline" size={18} color="#8D641C" />
                        <Text style={styles.abstainCardText}>
                          "{item.query}" için güvenli katalog eşleşmesi bulunamadı. Yanlış bir adayı seçmek zorunda değilsiniz.
                        </Text>
                      </View>
                      <Pressable
                        accessibilityRole="button"
                        accessibilityLabel={t("removeItem")}
                        style={styles.removeItemBtn}
                        onPress={() => onRemoveItem?.(index)}
                      >
                        <Ionicons name="trash-outline" size={13} color={colors.terracotta} />
                        <Text style={styles.removeItemBtnText}>Kaldır</Text>
                      </Pressable>
                    </View>
                  ) : null}

                  {/* Item Macro Grid */}
                  {!isAbstain ? (
                    <View style={styles.nutritionCard}>
                      {isUnverifiedEstimate && item.nutrition_estimate ? (
                        <View style={styles.acceptedEstimateNotice}>
                          <Text style={styles.unverifiedEstimateWarning}>AI tahmini — doğrulanmış katalog veya laboratuvar verisi değildir.</Text>
                          <Text style={styles.unverifiedEstimateKcal}>
                            {item.nutrition_estimate.kcal.low}–{item.nutrition_estimate.kcal.high} kcal
                          </Text>
                          {item.nutrition_estimate.assumptions.map((assumption) => (
                            <Text key={assumption} style={styles.unverifiedEstimateAssumption}>• {assumption}</Text>
                          ))}
                        </View>
                      ) : null}
                      <View style={styles.nutritionGrid}>
                        <View style={[styles.nutritionMetric, styles.nutritionMetricEnergy]}>
                          <Text style={styles.nutritionMetricValue}>≈ {previewKcal} kcal</Text>
                          <Text style={styles.nutritionMetricLabel}>{t("calories")}</Text>
                        </View>
                        <View style={styles.nutritionMetric}>
                          <Text style={styles.nutritionMetricValue}>≈ {previewProtein} g</Text>
                          <Text style={styles.nutritionMetricLabel}>{t("protein")}</Text>
                        </View>
                        <View style={styles.nutritionMetric}>
                          <Text style={styles.nutritionMetricValue}>≈ {previewCarb} g</Text>
                          <Text style={styles.nutritionMetricLabel}>{t("carbs")}</Text>
                        </View>
                        <View style={styles.nutritionMetric}>
                          <Text style={styles.nutritionMetricValue}>≈ {previewFat} g</Text>
                          <Text style={styles.nutritionMetricLabel}>{t("fat")}</Text>
                        </View>
                      </View>
                    </View>
                  ) : null}

                  {/* Quick Action Toggle Buttons (ONLY FOR MATCHED FOODS) */}
                  {!isAbstain ? (
                    <View style={styles.itemQuickActionRow}>
                      {!isUnverifiedEstimate ? (
                        <Pressable
                          style={[styles.itemQuickActionBtn, shouldShowPortion && styles.itemQuickActionBtnActive]}
                          onPress={() => setShowPortionEdit((prev) => ({ ...prev, [index]: !prev[index] }))}
                        >
                          <Ionicons name="scale-outline" size={13} color={shouldShowPortion ? colors.moss : colors.ink} />
                          <Text style={[styles.itemQuickActionBtnText, shouldShowPortion && styles.itemQuickActionBtnTextActive]}>
                            {shouldShowPortion ? "Porsiyonu Gizle" : "Porsiyonu Ayarla"}
                          </Text>
                        </Pressable>
                      ) : null}

                      {item.candidates.length > 1 ? (
                        <Pressable
                          style={[styles.itemQuickActionBtn, shouldShowCandidates && styles.itemQuickActionBtnActive]}
                          onPress={() => setShowCandidateEdit((prev) => ({ ...prev, [index]: !prev[index] }))}
                        >
                          <Ionicons name="swap-horizontal-outline" size={13} color={shouldShowCandidates ? colors.moss : colors.ink} />
                          <Text style={[styles.itemQuickActionBtnText, shouldShowCandidates && styles.itemQuickActionBtnTextActive]}>
                            {shouldShowCandidates ? "Değiştirmeyi Kapat" : "Değiştir"}
                          </Text>
                        </Pressable>
                      ) : (
                        <Pressable
                          style={[styles.itemQuickActionBtn, customSearchIndex === index && styles.itemQuickActionBtnActive]}
                          onPress={() => setCustomSearchIndex(customSearchIndex === index ? null : index)}
                        >
                          <Ionicons name="swap-horizontal-outline" size={13} color={customSearchIndex === index ? colors.moss : colors.ink} />
                          <Text style={[styles.itemQuickActionBtnText, customSearchIndex === index && styles.itemQuickActionBtnTextActive]}>
                            Değiştir
                          </Text>
                        </Pressable>
                      )}

                      {meal.items.length > 1 && onRemoveItem ? (
                        <Pressable
                          style={[styles.itemQuickActionBtn, styles.itemQuickActionBtnDanger]}
                          onPress={() => onRemoveItem(index)}
                        >
                          <Ionicons name="trash-outline" size={13} color={colors.terracotta} />
                          <Text style={[styles.itemQuickActionBtnText, { color: colors.terracotta }]}>Kaldır</Text>
                        </Pressable>
                      ) : null}
                    </View>
                  ) : null}

                  {/* Count Selection (when clarification is count) */}
                  {clarification?.kind === "count" && shouldShowPortion ? (
                    <View style={[styles.portionCardUnified, !hasQuantityEdit && styles.portionCardPending]}>
                      <View style={styles.portionHeaderPromptRow}>
                        {!hasQuantityEdit ? (
                          <Ionicons name="help-circle-outline" size={13} color="#8D641C" />
                        ) : null}
                        <Text style={[styles.portionSectionLabel, !hasQuantityEdit && styles.portionSectionLabelPending]}>
                          {!hasQuantityEdit ? "LÜTFEN PORSİYON MİKTARINI SEÇİN:" : "ADET / MİKTAR SEÇİMİ"}
                        </Text>
                      </View>
                      <View style={styles.presetPillsRow}>
                        {clarification.options.map((option) => {
                          const isSelected = hasQuantityEdit && quantity === option;
                          return (
                            <Pressable
                              key={option === null ? "unknown" : option}
                              accessibilityRole="button"
                              accessibilityLabel={option === null ? t("clarifyNotSure") : t("countChoice", { count: option, unit: formatLocalizedUnit(clarification.unit ?? "") })}
                              style={[styles.presetPill, isSelected && styles.presetPillActive]}
                              hitSlop={{ top: 6, bottom: 6, left: 6, right: 6 }}
                              onPress={() => setQuantityEdits((current) => ({ ...current, [index]: option }))}
                            >
                              <Text style={[styles.presetPillText, isSelected && styles.presetPillTextActive]}>
                                {option === null ? t("clarifyNotSure") : t("countChoice", { count: option, unit: formatLocalizedUnit(clarification.unit ?? "") })}
                              </Text>
                            </Pressable>
                          );
                        })}
                      </View>

                      <View style={styles.stepperInlineRow}>
                        <Text style={styles.stepperInlineLabel}>Özel miktar:</Text>
                        <View style={styles.stepperInlineControl}>
                          <Pressable
                            style={styles.stepperBtnSmall}
                            accessibilityLabel="Adet azalt"
                            onPress={() => {
                              const currentVal = typeof quantity === "number" ? quantity : 1;
                              setQuantityEdits((current) => ({ ...current, [index]: Math.max(1, currentVal - 1) }));
                            }}
                          >
                            <Ionicons name="remove" size={15} color={colors.ink} />
                          </Pressable>
                          <TextInput
                            style={styles.stepperInputSmall}
                            keyboardType="number-pad"
                            value={typeof quantity === "number" ? String(quantity) : ""}
                            placeholder="1"
                            placeholderTextColor={colors.muted}
                            maxLength={2}
                            onChangeText={(txt) => {
                              const clean = txt.replace(/[^0-9]/g, "");
                              const num = parseInt(clean, 10);
                              if (num > 0 && num <= 99) {
                                setQuantityEdits((current) => ({ ...current, [index]: num }));
                              } else if (clean === "") {
                                setQuantityEdits((current) => ({ ...current, [index]: null }));
                              }
                            }}
                          />
                          <Text style={styles.stepperUnitSmall}>{formatLocalizedUnit(clarification.unit ?? "adet")}</Text>
                          <Pressable
                            style={styles.stepperBtnSmall}
                            accessibilityLabel="Adet artır"
                            onPress={() => {
                              const currentVal = typeof quantity === "number" ? quantity : 1;
                              setQuantityEdits((current) => ({ ...current, [index]: Math.min(99, currentVal + 1) }));
                            }}
                          >
                            <Ionicons name="add" size={15} color={colors.ink} />
                          </Pressable>
                        </View>
                      </View>
                    </View>
                  ) : null}

                  {/* Unified Portion & Grams Control (Shown if toggled) */}
                  {shouldShowPortion && clarification?.kind !== "count" ? (
                    <View style={styles.portionCardUnified}>
                      <View style={styles.portionHeaderRow}>
                        <Text style={styles.portionSectionLabel}>PORSIYON & GRAMAJ AYARI</Text>
                        <View style={styles.gramsPillBadge} accessibilityLabel={hasRange ? t("portionBand", { grams: Math.round(grams), low: effectiveLow, high: effectiveHigh }) : undefined}>
                          <Text style={styles.gramsPillValue}>{Math.round(grams)} g</Text>
                          {hasRange ? <Text style={styles.gramsPillRange}>({effectiveLow}–{effectiveHigh}g)</Text> : null}
                        </View>
                      </View>

                      {hasRange ? (
                        <>
                          {/* 3 Sleek Preset Pills */}
                          <View style={styles.presetPillsRow}>
                            <Pressable
                              style={[styles.presetPill, grams === effectiveLow && styles.presetPillActive]}
                              onPress={() => setPortionQuick(index, effectiveLow)}
                            >
                              <Text style={[styles.presetPillText, grams === effectiveLow && styles.presetPillTextActive]}>
                                Az ({effectiveLow}g)
                              </Text>
                            </Pressable>
                            <Pressable
                              style={[styles.presetPill, grams === Math.round(baseGrams * quantityRatio) && styles.presetPillActive]}
                              onPress={() => setPortionQuick(index, Math.round(baseGrams * quantityRatio))}
                            >
                              <Text style={[styles.presetPillText, grams === Math.round(baseGrams * quantityRatio) && styles.presetPillTextActive]}>
                                Standart ({Math.round(baseGrams * quantityRatio)}g)
                              </Text>
                            </Pressable>
                            <Pressable
                              style={[styles.presetPill, grams === effectiveHigh && styles.presetPillActive]}
                              onPress={() => setPortionQuick(index, effectiveHigh)}
                            >
                              <Text style={[styles.presetPillText, grams === effectiveHigh && styles.presetPillTextActive]}>
                                Çok ({effectiveHigh}g)
                              </Text>
                            </Pressable>
                          </View>

                          {/* Minimalist Hairline Slider */}
                          <View style={styles.sliderContainer}>
                            <PortionSlider
                              minimumValue={effectiveLow}
                              maximumValue={effectiveHigh}
                              value={grams}
                              minimumTrackTintColor={colors.moss}
                              maximumTrackTintColor="#DFDDD5"
                              thumbTintColor={colors.moss}
                              onValueChange={(value) => {
                                setPortionEdits((current) => ({ ...current, [index]: Math.round(value) }));
                              }}
                              accessibilityLabel={t("portionFor", { query: item.query })}
                            />
                            <View style={styles.rangeLabelsMini}>
                              <Text style={styles.rangeTextMini}>{effectiveLow} g</Text>
                              <Text style={styles.rangeTextMini}>{effectiveHigh} g</Text>
                            </View>
                          </View>
                        </>
                      ) : (
                        <Text style={styles.mutedNote}>{t("portionPending")}</Text>
                      )}

                      {/* Direct Custom Grams Input Stepper */}
                      <View style={styles.stepperInlineRow}>
                        <Text style={styles.stepperInlineLabel}>İstediğiniz Gramaj:</Text>
                        <View style={styles.stepperInlineControl}>
                          <Pressable
                            style={styles.stepperBtnSmall}
                            accessibilityLabel="Gram azalt"
                            onPress={() => {
                              const currentGrams = grams > 0 ? grams : Math.round(baseGrams);
                              const nextVal = Math.max(10, currentGrams - 10);
                              setPortionEdits((current) => ({ ...current, [index]: nextVal }));
                            }}
                          >
                            <Ionicons name="remove" size={15} color={colors.ink} />
                          </Pressable>
                          <TextInput
                            style={styles.stepperInputGrams}
                            keyboardType="number-pad"
                            value={grams > 0 ? String(Math.round(grams)) : ""}
                            placeholder={String(Math.round(baseGrams))}
                            placeholderTextColor={colors.muted}
                            maxLength={4}
                            onChangeText={(txt) => {
                              const clean = txt.replace(/[^0-9]/g, "");
                              const num = parseInt(clean, 10);
                              if (num > 0 && num <= 9999) {
                                setPortionEdits((current) => ({ ...current, [index]: num }));
                              } else if (clean === "") {
                                setPortionEdits((current) => ({ ...current, [index]: 0 }));
                              }
                            }}
                          />
                          <Text style={styles.stepperUnitSmall}>g</Text>
                          <Pressable
                            style={styles.stepperBtnSmall}
                            accessibilityLabel="Gram artır"
                            onPress={() => {
                              const currentGrams = grams > 0 ? grams : Math.round(baseGrams);
                              const nextVal = Math.min(2500, currentGrams + 10);
                              setPortionEdits((current) => ({ ...current, [index]: nextVal }));
                            }}
                          >
                            <Ionicons name="add" size={15} color={colors.ink} />
                          </Pressable>
                        </View>
                      </View>
                    </View>
                  ) : null}

                  {/* Alternative Food Candidates & "+ Başka..." Search / Custom Entry */}
                  {shouldShowCandidates ? (
                    <View style={styles.alternatesBlock}>
                      <Text style={styles.portionSectionLabel}>
                        {isAbstain ? "GÜVENLİ EŞLEŞME BULUNAMADI" : "BU YEMEĞİ DEĞİŞTİR / EŞLEŞTİR"}
                      </Text>

                      {/* Catalogue misses stay unresolved until the user chooses a catalogue item or enters calories. */}
                      {isAbstain ? (
                        <View style={styles.aiEstimateRowCard}>
                          <View style={styles.aiEstimateRowHeader}>
                            <View style={styles.aiBadgeSmall}>
                              <Ionicons name="shield-outline" size={12} color="#8D641C" />
                              <Text style={styles.aiBadgeSmallText}>Doğrulanmış değer yok</Text>
                            </View>
                            <Text style={styles.aiKatalogDisiText}>Katalogda Yok</Text>
                          </View>
                          <Text style={styles.customNotFoundText}>
                            Katalog doğrulaması yok. Gemini tahmini ayrı ve doğrulanmamış gösterilir; siz onaylamadan kaydedilmez.
                          </Text>
                          {nutritionEstimates[index] ? (
                            <View style={styles.unverifiedEstimateBox}>
                              <Text style={styles.unverifiedEstimateBadge}>AI TAHMİNİ · DOĞRULANMAMIŞ</Text>
                              <Text style={styles.unverifiedEstimateTitle}>{nutritionEstimates[index].dish_name}</Text>
                              <Text style={styles.unverifiedEstimateKcal}>
                                ≈ {nutritionEstimates[index].kcal.midpoint} kcal ({nutritionEstimates[index].kcal.low}–{nutritionEstimates[index].kcal.high})
                              </Text>
                              <Text style={styles.unverifiedEstimateMacros}>
                                Protein {nutritionEstimates[index].protein_g.low}–{nutritionEstimates[index].protein_g.high} g · Karb {nutritionEstimates[index].carb_g.low}–{nutritionEstimates[index].carb_g.high} g · Yağ {nutritionEstimates[index].fat_g.low}–{nutritionEstimates[index].fat_g.high} g
                              </Text>
                              {nutritionEstimates[index].assumptions.map((assumption) => (
                                <Text key={assumption} style={styles.unverifiedEstimateAssumption}>• {assumption}</Text>
                              ))}
                              <Text style={styles.unverifiedEstimateWarning}>
                                AI tahmini — doğrulanmış katalog veya laboratuvar verisi değildir.
                              </Text>
                              <Pressable
                                style={styles.unverifiedEstimateAccept}
                                onPress={() => onAcceptEstimate?.(index, nutritionEstimates[index])}
                                accessibilityRole="button"
                                accessibilityLabel="Doğrulanmamış AI tahminini kullan"
                              >
                                <Text style={styles.unverifiedEstimateAcceptText}>Bu tahmini kullan</Text>
                              </Pressable>
                            </View>
                          ) : estimateErrors[index] ? (
                            <Pressable
                              style={styles.unverifiedEstimateRequest}
                              onPress={() => void requestNutritionEstimates([index])}
                              accessibilityRole="button"
                              accessibilityLabel="Gemini tahminini yeniden dene"
                            >
                              <Ionicons name="sparkles-outline" size={15} color={colors.white} />
                              <Text style={styles.unverifiedEstimateRequestText}>Yeniden dene</Text>
                            </Pressable>
                          ) : (
                            <View style={styles.unverifiedEstimatePreparing}>
                              <Ionicons name="sparkles-outline" size={15} color="#8D641C" />
                              <Text style={styles.unverifiedEstimatePreparingText}>
                                {estimateLoading[index] ? "AI tahmini hazırlanıyor…" : "AI tahmini sıraya alındı…"}
                              </Text>
                            </View>
                          )}
                          {estimateErrors[index] ? <Text style={styles.estimateError}>{estimateErrors[index]}</Text> : null}
                        </View>
                      ) : null}

                      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chipsRow}>
                        {candidateChoices.map((candidate) => {
                          const isSelected = selected === candidate.food_id;
                          return (
                            <Pressable key={candidate.food_id} onPress={() => onChooseCandidate(index, candidate)} style={[styles.chip, isSelected && styles.chipSelected]}>
                              <Text style={[styles.chipText, isSelected && styles.chipTextSelected]}>{candidate.name}</Text>
                            </Pressable>
                          );
                        })}

                        {/* "+ Başka..." Chip Button */}
                        <Pressable
                          style={[styles.chip, styles.chipOther, customSearchIndex === index && styles.chipSelected]}
                          onPress={() => {
                            setCustomSearchIndex(customSearchIndex === index ? null : index);
                            setCustomFoodQuery("");
                            setCustomNotFound(false);
                          }}
                        >
                          <Ionicons name="swap-horizontal-outline" size={13} color={colors.moss} />
                          <Text style={[styles.chipText, { color: colors.moss, fontWeight: "800" }]}>+ Değiştir...</Text>
                        </Pressable>
                      </ScrollView>

                      {/* Custom Food Search / Manual Entry Sub-Panel */}
                      {customSearchIndex === index ? (
                        <View style={styles.customFoodBox}>
                          <Text style={styles.customFoodBoxTitle}>Farklı Bir Yemek Ara veya Ekle</Text>
                          <View style={styles.customFoodInputRow}>
                            <TextInput
                              style={styles.customFoodInput}
                              placeholder="Yemek adını yazın (örn. Menemen)..."
                              placeholderTextColor={colors.muted}
                              value={customFoodQuery}
                              onChangeText={(t) => {
                                setCustomFoodQuery(t);
                                setCustomNotFound(false);
                              }}
                            />
                            <Pressable style={styles.customFoodSearchBtn} onPress={() => handleSearchCustomFood(index)}>
                              <Ionicons name="search" size={14} color={colors.white} />
                              <Text style={styles.customFoodSearchBtnText}>Ara</Text>
                            </Pressable>
                          </View>

                          {customNotFound ? (
                            <View style={styles.customNotFoundCard}>
                              <Ionicons name="information-circle-outline" size={16} color="#8D641C" />
                              <Text style={styles.customNotFoundText}>
                                "{customFoodQuery}" resmi katalogda bulunamadı. Besin değerlerini kendiniz girmek ister misiniz?
                              </Text>

                              <View style={styles.manualKcalRow}>
                                <Text style={styles.manualKcalLabel}>Bildiğiniz kalori:</Text>
                                <TextInput
                                  style={styles.manualKcalInput}
                                  keyboardType="number-pad"
                                  value={customCaloriesInput}
                                  onChangeText={setCustomCaloriesInput}
                                  placeholder="Örn. 350"
                                />
                                <Text style={styles.manualKcalUnit}>kcal</Text>
                              </View>

                              <Pressable style={styles.saveManualDishBtn} onPress={() => handleSaveCustomManualDish(index)}>
                                <Ionicons name="checkmark-circle-outline" size={15} color={colors.white} />
                                <Text style={styles.saveManualDishBtnText}>Özel Yemek Olarak Ekle</Text>
                              </Pressable>
                            </View>
                          ) : null}
                        </View>
                      ) : null}
                    </View>
                  ) : null}

                  {/* Provenance Audit Row - Strictly Collapsed by Default */}
                  <Pressable style={styles.whyRow} onPress={() => toggleAudit(index)}>
                    <View style={styles.whyIcon}><Ionicons name="finger-print-outline" size={15} color={colors.moss} /></View>
                    <View style={styles.whyCopy}><Text style={styles.whyTitle}>{t("whyResult")}</Text><Text style={styles.whySubtitle}>{t("traceDecision")}</Text></View>
                    <Ionicons name={isAuditExpanded ? "chevron-up" : "chevron-down"} size={16} color={colors.muted} />
                  </Pressable>
                  {isAuditExpanded ? (
                    <View style={styles.auditBox}>
                      <AuditRow
                        label={t("matchedFoodId")}
                        value={displayName}
                        badge={selected !== "ABSTAIN" ? selected : undefined}
                      />
                      <AuditRow
                        label={t("sourceDatabase")}
                        value={item.source_database === "TURKOMP" ? "TÜRKOMP (Ulusal Veri Tabanı)" : item.source_database ?? t("catalogueProvenance")}
                      />
                      <AuditRow
                        label={t("confidence")}
                        value={
                          item.confidence >= 0.95
                            ? "%98 (Referans Standart)"
                            : item.confidence >= 0.80
                            ? `%${Math.round(item.confidence * 100)} (Yüksek)`
                            : `%${Math.round(item.confidence * 100)} (Orta)`
                        }
                      />
                      {item.capture_medium && item.capture_medium !== "real_plate" ? (
                        <AuditRow label={t("captureMedium")} value={item.capture_medium} />
                      ) : null}

                      <AuditRow label={t("quantity")} value={displayedQuantity} />
                      <AuditRow label={t("exactGrams")} value={grams ? `${Math.round(grams)} g` : t("pending")} />
                      <AuditRow
                        label={t("portionSource")}
                        value={formatLocalizedProvenance(item.portion_source)}
                      />
                      <AuditRow
                        label={t("portionProvenance")}
                        value={item.portion_provenance?.includes("default_serving") ? `Katalog tanımı (${Math.round(grams)} g)` : item.portion_provenance ?? t("pending")}
                      />
                    </View>
                  ) : null}
                </View>
              ) : null}
            </View>
          );
        })}

        {/* + Tabağa Öğe Ekle (Add Food / Drink to Plate) */}
        <View style={styles.addPlateItemContainer}>
          {!showAddPlateItem ? (
            <Pressable
              style={styles.addPlateItemHeroBtn}
              onPress={() => setShowAddPlateItem(true)}
              accessibilityRole="button"
              accessibilityLabel="Tabağa Öğe Ekle"
            >
              <View style={styles.addPlateItemIconCircle}>
                <Ionicons name="add" size={18} color={colors.moss} />
              </View>
              <View style={styles.addPlateItemCopy}>
                <Text style={styles.addPlateItemTitle}>Tabağa Başka Bir Öğe Ekle</Text>
                <Text style={styles.addPlateItemSubtitle}>İçecek, ekmek, salata veya eksik yemek ekleyin</Text>
              </View>
            </Pressable>
          ) : (
            <View style={styles.addPlateItemCard}>
              <View style={styles.addPlateItemCardHeader}>
                <View style={styles.addPlateItemHeaderLeft}>
                  <Ionicons name="restaurant-outline" size={16} color={colors.moss} />
                  <Text style={styles.addPlateItemCardTitle}>Tabağa Yeni Öğe Ekle</Text>
                </View>
                <Pressable onPress={() => { setShowAddPlateItem(false); setNewPlateItemNotFound(false); }}>
                  <Ionicons name="close-circle" size={20} color={colors.muted} />
                </Pressable>
              </View>

              {/* Quick Suggestion Chips */}
              <Text style={styles.quickAddLabel}>HIZLI EKLE:</Text>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.quickAddChipsRow}>
                {[
                  { name: "Ayran", icon: "🥛" },
                  { name: "Ekmek", icon: "🍞" },
                  { name: "Çoban Salatası", icon: "🥗" },
                  { name: "Yoğurt", icon: "🥣" },
                  { name: "Burger / Köfte", icon: "🍔" },
                  { name: "Pizza", icon: "🍕" },
                  { name: "Makarna", icon: "🍝" },
                  { name: "Pirinç pilavı", icon: "🍚" },
                ].map((quick) => (
                  <Pressable
                    key={quick.name}
                    style={styles.quickAddChip}
                    onPress={() => {
                      void Promise.resolve(onAddItem?.(quick.name));
                      setShowAddPlateItem(false);
                    }}
                  >
                    <Text style={styles.quickAddChipText}>{quick.icon} + {quick.name}</Text>
                  </Pressable>
                ))}
              </ScrollView>

              {/* Direct Search Input */}
              <View style={styles.addPlateItemInputRow}>
                <TextInput
                  style={styles.addPlateItemInput}
                  placeholder="Yemek veya içecek adı yazın (örn. Menemen)..."
                  placeholderTextColor={colors.muted}
                  value={newPlateItemQuery}
                  onChangeText={(t) => {
                    setNewPlateItemQuery(t);
                    setNewPlateItemNotFound(false);
                  }}
                  autoFocus
                />
                <Pressable
                  style={styles.addPlateItemSubmitBtn}
                  onPress={() => {
                    const trimmed = newPlateItemQuery.trim();
                    if (!trimmed) {
                      Alert.alert("Yemek Adı Gerekli", "Lütfen eklemek istediğiniz yemeği yazın.");
                      return;
                    }
                    // The catalogue decides whether this name exists. The form
                    // stays open while the lookup runs, and an abstention opens the
                    // manual-entry branch (no invented row, no invented calories).
                    void Promise.resolve(onAddItem?.(trimmed)).then((added) => {
                      if (added) {
                        setNewPlateItemQuery("");
                        setShowAddPlateItem(false);
                        setNewPlateItemNotFound(false);
                      } else {
                        setNewPlateItemNotFound(true);
                      }
                    });
                  }}
                >
                  <Ionicons name="add" size={16} color={colors.white} />
                  <Text style={styles.addPlateItemSubmitBtnText}>Ekle</Text>
                </Pressable>
              </View>

              {/* If not found in catalogue, allow custom kcal entry */}
              {newPlateItemNotFound ? (
                <View style={styles.customNotFoundCard}>
                  <Ionicons name="information-circle-outline" size={16} color="#8D641C" />
                  <Text style={styles.customNotFoundText}>
                    "{newPlateItemQuery}" katalogda bulunamadı. Tahmini kalori girerek ekleyebilirsiniz:
                  </Text>
                  <View style={styles.manualKcalRow}>
                    <Text style={styles.manualKcalLabel}>Kalori:</Text>
                    <TextInput
                      style={styles.manualKcalInput}
                      keyboardType="number-pad"
                      value={newPlateItemKcal}
                      onChangeText={setNewPlateItemKcal}
                      placeholder="200"
                    />
                    <Text style={styles.manualKcalUnit}>kcal</Text>
                  </View>
                  <Pressable
                    style={styles.saveManualDishBtn}
                    onPress={() => {
                      const kcal = parseInt(newPlateItemKcal, 10);
                      if (!Number.isFinite(kcal) || kcal <= 0 || kcal > 5000) {
                        Alert.alert("Geçersiz kalori", "1–5000 arasında bir kalori değeri girin.");
                        return;
                      }
                      void Promise.resolve(onAddItem?.(newPlateItemQuery.trim(), kcal));
                      setNewPlateItemQuery("");
                      setNewPlateItemKcal("");
                      setNewPlateItemNotFound(false);
                      setShowAddPlateItem(false);
                    }}
                  >
                    <Ionicons name="checkmark-circle-outline" size={15} color={colors.white} />
                    <Text style={styles.saveManualDishBtnText}>Tabağa Ekle</Text>
                  </Pressable>
                </View>
              ) : null}
            </View>
          )}
        </View>

        <Pressable style={styles.textButton} onPress={onBack}>
          <Ionicons name="camera-outline" size={16} color={colors.ink} />
          <Text style={styles.textButtonLabel}>{t("captureAnother")}</Text>
        </Pressable>
      </ScrollView>

      {/* Sticky Bottom Action Footer */}
      <View style={styles.stickyFooter}>
        {footerHint ? <Text style={styles.footerHint}>{footerHint}</Text> : null}
        <Pressable
          style={[styles.primaryButton, isSaveDisabled && styles.primaryButtonDisabled]}
          onPress={handleSave}
          disabled={saving}
          accessibilityRole="button"
        >
          <Text style={[styles.primaryButtonText, isSaveDisabled && styles.primaryButtonTextDisabled]}>
            {saving
              ? t("saving")
              : isSaved
              ? t("saveCorrection")
              : hasUnresolvedAbstain
              ? "Kayıt için öğe kararlarını tamamlayın"
              : hasPendingQuestions
              ? t("saveQuestion")
              : t("saveToday")}
          </Text>
          <Ionicons name="arrow-forward" size={19} color={isSaveDisabled ? "#A8A294" : colors.white} />
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.paper, overflow: "hidden" },
  scroll: { flex: 1 },
  content: { padding: 18, paddingBottom: 24 },
  deferredValuesCard: { display: "none" },
  statusBadgesRow: { flexDirection: "row", alignItems: "center" },
  stickyFooter: {
    paddingHorizontal: 18,
    paddingTop: 12,
    paddingBottom: 28,
    backgroundColor: colors.paper,
    borderTopWidth: 1,
    borderTopColor: colors.line,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: -3 },
    shadowOpacity: 0.06,
    shadowRadius: 5,
    elevation: 8,
  },
  imageContainer: {
    width: "100%",
    height: 190,
    borderRadius: 20,
    overflow: "hidden",
    marginBottom: 14,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: "#1C211E",
    position: "relative",
    justifyContent: "center",
    alignItems: "center",
  },
  previewBackdrop: {
    ...StyleSheet.absoluteFillObject,
    width: "100%",
    height: "100%",
    opacity: 0.55,
  },
  previewImage: {
    width: "100%",
    height: "100%",
  },
  imageBadge: {
    position: "absolute",
    bottom: 10,
    left: 10,
    backgroundColor: "rgba(31, 36, 33, 0.82)",
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 12,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  imageBadgeText: {
    color: colors.white,
    fontSize: 11,
    fontWeight: "700",
  },
  degradedBanner: { flexDirection: "row", alignItems: "flex-start", gap: 10, backgroundColor: "#FBF1D8", borderRadius: 16, padding: 12, marginBottom: 12 },
  captureMediumBanner: { flexDirection: "row", alignItems: "flex-start", gap: 10, backgroundColor: "#FBF1D8", borderRadius: 16, padding: 12, marginBottom: 12 },
  degradedCopy: { flex: 1 },
  degradedTitle: { color: "#8D641C", fontSize: 12, fontWeight: "800" },
  degradedText: { color: colors.muted, fontSize: 11, lineHeight: 16, marginTop: 3 },

  // Modern Callout Banner (21st-dev inspiration)
  modernBannerCard: {
    borderRadius: 20,
    padding: 14,
    marginBottom: 14,
    backgroundColor: colors.card,
    borderWidth: 1.5,
    borderColor: "rgba(0, 0, 0, 0.08)",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 3 },
    shadowOpacity: 0.04,
    shadowRadius: 8,
    elevation: 2,
  },
  modernBannerAsk: {
    backgroundColor: "#FDFBF5",
    borderColor: "#E8B653",
  },
  modernBannerAccept: {
    backgroundColor: "#F3F8F4",
    borderColor: "#A3D2B3",
  },
  modernBannerReview: {
    backgroundColor: "#F8F7F4",
    borderColor: colors.line,
  },
  modernBannerTopRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 8,
  },
  modernBannerBadgeWrap: {
    flexDirection: "row",
    alignItems: "center",
    gap: 7,
  },
  modernBannerIconCircle: {
    width: 26,
    height: 26,
    borderRadius: 13,
    backgroundColor: colors.paper,
    alignItems: "center",
    justifyContent: "center",
  },
  modernIconCircleAsk: {
    backgroundColor: "#FBF1D8",
  },
  modernIconCircleAccept: {
    backgroundColor: "#E2F0E7",
  },
  modernIconCircleReview: {
    backgroundColor: colors.paper,
  },
  modernBannerCategoryTag: {
    fontSize: 10,
    fontWeight: "900",
    letterSpacing: 0.8,
    color: colors.muted,
  },
  categoryTagAsk: {
    color: "#8D641C",
  },
  categoryTagAccept: {
    color: colors.moss,
  },
  modernPendingPill: {
    backgroundColor: "#FBF1D8",
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "#E8B653",
  },
  modernPendingPillText: {
    color: "#8D641C",
    fontSize: 10,
    fontWeight: "800",
  },
  modernBannerMainTitle: {
    fontSize: 15,
    fontWeight: "900",
    color: colors.ink,
    marginBottom: 6,
    letterSpacing: -0.2,
  },
  modernBannerDescription: {
    fontSize: 12,
    lineHeight: 17,
    color: colors.muted,
    fontWeight: "500",
  },
  modernPillsGroup: {
    marginTop: 4,
    gap: 6,
  },
  modernPillCategoryRow: {
    flexDirection: "row",
    alignItems: "center",
    flexWrap: "wrap",
    gap: 6,
  },
  modernPillGroupLabel: {
    fontSize: 11,
    fontWeight: "800",
    color: colors.muted,
    minWidth: 54,
  },
  modernItemTagsRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 5,
    flex: 1,
  },
  modernUnmatchedTag: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: "#FDF0ED",
    borderWidth: 1,
    borderColor: "#F7D0C5",
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 8,
  },
  modernUnmatchedTagText: {
    color: colors.terracotta,
    fontSize: 11,
    fontWeight: "800",
  },
  modernCountTag: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: "#FBF1D8",
    borderWidth: 1,
    borderColor: "#EBD292",
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 8,
  },
  modernCountTagText: {
    color: "#7E5813",
    fontSize: 11,
    fontWeight: "800",
  },
  modernTagEmoji: {
    fontSize: 12,
  },

  // Bento Macro Summary Bar
  bentoSummaryCard: {
    backgroundColor: colors.card,
    borderRadius: 18,
    borderWidth: 1,
    borderColor: colors.line,
    padding: 14,
    marginBottom: 16,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.04,
    shadowRadius: 4,
    elevation: 2,
  },
  bentoSummaryHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 10,
    paddingBottom: 8,
    borderBottomWidth: 1,
    borderBottomColor: colors.paper,
  },
  bentoKcalBadge: {
    flexDirection: "row",
    alignItems: "baseline",
    gap: 5,
  },
  bentoKcalValue: {
    fontSize: 22,
    fontWeight: "900",
    color: colors.ink,
  },
  bentoKcalUnit: {
    fontSize: 12,
    fontWeight: "700",
    color: colors.terracotta,
  },
  bentoItemCountBadge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: colors.mossSoft,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 10,
  },
  bentoItemCountText: {
    fontSize: 11,
    fontWeight: "800",
    color: colors.moss,
  },
  bentoMacroRow: {
    flexDirection: "row",
    gap: 8,
  },
  bentoMacroPill: {
    flex: 1,
    backgroundColor: colors.paper,
    borderRadius: 12,
    paddingVertical: 7,
    paddingHorizontal: 8,
    alignItems: "center",
  },
  bentoMacroLabel: {
    fontSize: 10,
    fontWeight: "800",
    color: colors.muted,
  },
  bentoMacroValue: {
    fontSize: 13,
    fontWeight: "800",
    color: colors.ink,
    marginTop: 2,
  },

  // Items Section Header
  itemsSectionHeader: {
    marginBottom: 10,
  },
  itemsSectionTitle: {
    fontSize: 13,
    fontWeight: "800",
    color: colors.ink,
    letterSpacing: 0.2,
  },
  itemsSectionSubtitle: {
    fontSize: 11,
    color: colors.muted,
    marginTop: 2,
  },

  // Item Accordion Card
  itemCard: {
    backgroundColor: colors.card,
    borderRadius: 18,
    borderWidth: 1,
    borderColor: colors.line,
    marginBottom: 10,
    overflow: "hidden",
  },
  itemCardExpanded: {
    borderColor: colors.mossSoft,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.05,
    shadowRadius: 5,
    elevation: 3,
  },
  itemAccordionHeader: {
    flexDirection: "row",
    alignItems: "center",
    padding: 13,
  },
  itemEmojiWrap: {
    width: 36,
    height: 36,
    borderRadius: 12,
    backgroundColor: colors.paper,
    alignItems: "center",
    justifyContent: "center",
  },
  itemEmojiText: {
    fontSize: 19,
  },
  itemNameWrap: {
    flex: 1,
    minWidth: 0,
    marginLeft: 10,
  },
  itemMatch: {
    color: colors.ink,
    fontSize: 14,
    fontWeight: "800",
  },
  itemHeaderSubRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginTop: 3,
  },
  quantityText: {
    color: colors.muted,
    fontSize: 11,
    fontWeight: "600",
  },
  confidencePillMini: {
    borderRadius: 6,
    paddingHorizontal: 5,
    paddingVertical: 2,
  },
  confidenceTextMini: {
    fontSize: 9,
    fontWeight: "800",
  },
  itemHeaderRight: {
    alignItems: "flex-end",
    gap: 3,
    marginLeft: 8,
  },
  itemHeaderKcalChevronRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  itemHeaderKcal: {
    color: colors.terracotta,
    fontSize: 12,
    fontWeight: "800",
  },
  itemHeaderKcalZero: {
    color: colors.muted,
  },
  itemHeaderMacrosMini: {
    fontSize: 10,
    fontWeight: "700",
    color: colors.muted,
    letterSpacing: 0.2,
  },
  chevronCircle: {
    width: 22,
    height: 22,
    borderRadius: 11,
    backgroundColor: colors.paper,
    alignItems: "center",
    justifyContent: "center",
  },

  // Expanded Body
  itemDetailsBody: {
    paddingHorizontal: 14,
    paddingBottom: 14,
    borderTopWidth: 1,
    borderTopColor: colors.paper,
  },

  nutritionCard: { backgroundColor: colors.paper, borderRadius: 14, padding: 10, marginTop: 10 },
  nutritionGrid: { flexDirection: "row", justifyContent: "space-between" },
  nutritionMetric: { flex: 1, borderLeftWidth: 2, borderLeftColor: colors.line, paddingLeft: 6, paddingVertical: 1 },
  nutritionMetricEnergy: { borderLeftColor: colors.terracotta },
  nutritionMetricValue: { color: colors.ink, fontSize: 12, fontWeight: "800" },
  nutritionMetricLabel: { color: colors.muted, fontSize: 9, fontWeight: "700", marginTop: 1 },

  confidenceHigh: { backgroundColor: colors.mossSoft },
  confidenceMed: { backgroundColor: "#FBF1D8" },
  confidenceLow: { backgroundColor: colors.terracottaSoft },
  confidenceTextHigh: { color: colors.moss },
  confidenceTextMed: { color: "#8D641C" },
  confidenceTextLow: { color: colors.terracotta },

  // Item Quick Action Buttons (Porsiyonu Ayarla & Yemeği Değiştir)
  itemQuickActionRow: {
    flexDirection: "row",
    gap: 8,
    marginTop: 10,
  },
  itemQuickActionBtn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 5,
    backgroundColor: colors.paper,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: colors.line,
    paddingVertical: 7,
  },
  itemQuickActionBtnActive: {
    backgroundColor: colors.mossSoft,
    borderColor: colors.moss,
  },
  itemQuickActionBtnText: {
    color: colors.ink,
    fontSize: 11,
    fontWeight: "700",
  },
  itemQuickActionBtnTextActive: {
    color: colors.moss,
    fontWeight: "800",
  },

  // Unified Portion Card
  portionCardUnified: {
    backgroundColor: colors.paper,
    borderRadius: 14,
    padding: 12,
    marginTop: 10,
    borderWidth: 1,
    borderColor: colors.line,
  },
  portionCardPending: {
    borderColor: "#E8B653",
    backgroundColor: "#FDFBF5",
  },
  portionHeaderPromptRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginBottom: 8,
  },
  portionSectionLabelPending: {
    color: "#8D641C",
    fontWeight: "900",
  },
  portionHeaderRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 8,
  },
  portionSectionLabel: {
    fontSize: 9,
    fontWeight: "800",
    color: colors.muted,
    letterSpacing: 1.2,
  },
  gramsPillBadge: {
    flexDirection: "row",
    alignItems: "baseline",
    gap: 4,
    backgroundColor: colors.card,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: colors.line,
  },
  gramsPillValue: {
    fontSize: 12,
    fontWeight: "800",
    color: colors.moss,
  },
  gramsPillRange: {
    fontSize: 10,
    color: colors.muted,
    fontWeight: "600",
  },
  presetPillsRow: {
    flexDirection: "row",
    gap: 6,
    marginBottom: 8,
  },
  presetPill: {
    flex: 1,
    minHeight: 34,
    backgroundColor: colors.card,
    borderRadius: 9,
    borderWidth: 1,
    borderColor: colors.line,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 4,
  },
  presetPillActive: {
    backgroundColor: colors.moss,
    borderColor: colors.moss,
  },
  presetPillText: {
    fontSize: 10,
    fontWeight: "700",
    color: colors.ink,
  },
  presetPillTextActive: {
    color: colors.white,
    fontWeight: "800",
  },
  sliderContainer: {
    marginVertical: 4,
  },
  rangeLabelsMini: {
    flexDirection: "row",
    justifyContent: "space-between",
    paddingHorizontal: 4,
    marginTop: -4,
  },
  rangeTextMini: {
    fontSize: 9,
    color: colors.muted,
    fontWeight: "600",
  },
  stepperInlineRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: 8,
    paddingTop: 8,
    borderTopWidth: 1,
    borderTopColor: "rgba(223, 221, 213, 0.7)",
  },
  stepperInlineLabel: {
    fontSize: 11,
    fontWeight: "700",
    color: colors.ink,
  },
  stepperInlineControl: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: colors.card,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: colors.line,
    paddingHorizontal: 2,
    paddingVertical: 1,
  },
  stepperBtnSmall: {
    width: 28,
    height: 28,
    borderRadius: 6,
    backgroundColor: colors.paper,
    alignItems: "center",
    justifyContent: "center",
  },
  stepperInputSmall: {
    minWidth: 28,
    height: 28,
    textAlign: "center",
    fontSize: 12,
    fontWeight: "800",
    color: colors.ink,
    paddingHorizontal: 2,
  },
  stepperInputGrams: {
    minWidth: 44,
    height: 28,
    textAlign: "center",
    fontSize: 13,
    fontWeight: "900",
    color: colors.moss,
    paddingHorizontal: 3,
  },
  stepperUnitSmall: {
    fontSize: 10,
    fontWeight: "700",
    color: colors.muted,
    marginRight: 4,
  },

  // AI Estimate Row Card (Inside item card for uncatalogued items)
  aiEstimateRowCard: {
    backgroundColor: "#FDFBF5",
    borderRadius: 12,
    borderWidth: 1.5,
    borderColor: "#E8B653",
    padding: 10,
    marginTop: 6,
    marginBottom: 8,
  },
  aiEstimateRowHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 8,
  },
  aiBadgeSmall: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: "#FBF1D8",
    paddingHorizontal: 7,
    paddingVertical: 3,
    borderRadius: 6,
  },
  aiBadgeSmallText: {
    color: "#8D641C",
    fontSize: 10,
    fontWeight: "800",
  },
  aiKatalogDisiText: {
    color: colors.muted,
    fontSize: 10,
    fontWeight: "700",
  },
  unverifiedEstimateRequest: {
    minHeight: 44,
    marginTop: 12,
    borderRadius: 12,
    backgroundColor: colors.moss,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 7,
    paddingHorizontal: 14,
  },
  unverifiedEstimateRequestText: { color: colors.white, fontSize: 13, fontWeight: "800" },
  unverifiedEstimatePreparing: {
    minHeight: 44,
    marginTop: 12,
    borderRadius: 12,
    backgroundColor: "#FBF1D8",
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 7,
    paddingHorizontal: 14,
  },
  unverifiedEstimatePreparingText: { color: "#8D641C", fontSize: 13, fontWeight: "800" },
  unverifiedEstimateBox: {
    marginTop: 12,
    borderTopWidth: 1,
    borderTopColor: "#E8B653",
    paddingTop: 12,
  },
  unverifiedEstimateBadge: {
    alignSelf: "flex-start",
    color: "#8D641C",
    backgroundColor: "#F7E8BC",
    borderRadius: 999,
    paddingHorizontal: 9,
    paddingVertical: 5,
    fontSize: 9,
    fontWeight: "900",
    letterSpacing: 0.7,
    marginBottom: 7,
  },
  unverifiedEstimateTitle: { color: colors.ink, fontSize: 15, fontWeight: "900" },
  unverifiedEstimateKcal: { color: colors.terracotta, fontSize: 18, fontWeight: "900", marginTop: 4 },
  unverifiedEstimateMacros: { color: colors.ink, fontSize: 12, lineHeight: 18, fontWeight: "700", marginTop: 6 },
  unverifiedEstimateAssumption: { color: colors.muted, fontSize: 11, lineHeight: 17, marginTop: 3 },
  unverifiedEstimateWarning: { color: "#8D641C", fontSize: 11, lineHeight: 16, fontWeight: "800", marginTop: 9 },
  unverifiedEstimateAccept: {
    minHeight: 44,
    marginTop: 10,
    borderRadius: 12,
    borderWidth: 1.5,
    borderColor: colors.terracotta,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 14,
  },
  unverifiedEstimateAcceptText: { color: colors.terracotta, fontSize: 13, fontWeight: "900" },
  estimateError: { color: colors.terracotta, fontSize: 11, lineHeight: 16, fontWeight: "700", marginTop: 8 },
  unverifiedInlineTag: { color: "#8D641C", fontSize: 10, fontWeight: "900", marginTop: 3, textAlign: "right" },
  acceptedEstimateNotice: {
    borderRadius: 12,
    backgroundColor: "#FBF1D8",
    borderWidth: 1,
    borderColor: "#E8B653",
    padding: 12,
    marginBottom: 12,
  },
  // Alternates Block
  alternatesBlock: {
    marginTop: 10,
  },
  chipsRow: { gap: 6, paddingTop: 4, paddingBottom: 2 },
  chip: { minHeight: 36, borderWidth: 1, borderColor: colors.line, borderRadius: 10, paddingHorizontal: 9, paddingVertical: 6, minWidth: 90, justifyContent: "center" },
  chipSelected: { borderColor: colors.moss, backgroundColor: colors.mossSoft },
  chipOther: { borderColor: colors.moss, borderStyle: "dashed", backgroundColor: colors.card, flexDirection: "row", alignItems: "center", gap: 4 },
  chipText: { color: colors.ink, fontSize: 11, fontWeight: "800" },
  chipTextSelected: { color: colors.moss },

  // Custom Food Search Box
  customFoodBox: {
    backgroundColor: colors.paper,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.line,
    padding: 10,
    marginTop: 8,
  },
  customFoodBoxTitle: {
    fontSize: 10,
    fontWeight: "800",
    color: colors.ink,
    marginBottom: 6,
  },
  customFoodInputRow: {
    flexDirection: "row",
    gap: 6,
  },
  customFoodInput: {
    flex: 1,
    minHeight: 34,
    backgroundColor: colors.card,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: colors.line,
    paddingHorizontal: 10,
    fontSize: 12,
    color: colors.ink,
  },
  customFoodSearchBtn: {
    backgroundColor: colors.moss,
    borderRadius: 8,
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 10,
    justifyContent: "center",
  },
  customFoodSearchBtnText: {
    color: colors.white,
    fontSize: 11,
    fontWeight: "800",
  },
  customNotFoundCard: {
    backgroundColor: "#FBF1D8",
    borderRadius: 10,
    padding: 10,
    marginTop: 8,
    gap: 6,
  },
  customNotFoundText: {
    color: "#8D641C",
    fontSize: 11,
    lineHeight: 15,
    fontWeight: "600",
  },
  manualKcalRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginTop: 4,
  },
  manualKcalLabel: {
    fontSize: 11,
    fontWeight: "700",
    color: colors.ink,
  },
  manualKcalInput: {
    width: 60,
    height: 28,
    backgroundColor: colors.card,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: colors.line,
    textAlign: "center",
    fontSize: 12,
    fontWeight: "800",
    color: colors.ink,
  },
  manualKcalUnit: {
    fontSize: 11,
    fontWeight: "700",
    color: colors.muted,
  },
  saveManualDishBtn: {
    backgroundColor: colors.terracotta,
    borderRadius: 8,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 5,
    paddingVertical: 7,
    marginTop: 4,
  },
  saveManualDishBtnText: {
    color: colors.white,
    fontSize: 11,
    fontWeight: "800",
  },

  abstainCardNotice: {
    backgroundColor: "#FBF1D8",
    borderRadius: 12,
    paddingHorizontal: 10,
    paddingVertical: 8,
    marginTop: 10,
    gap: 6,
  },
  abstainNoticeLeft: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 6,
    flex: 1,
  },
  abstainCardText: {
    color: "#8D641C",
    fontSize: 11,
    lineHeight: 15,
    fontWeight: "700",
    flex: 1,
  },
  removeItemBtn: {
    flexDirection: "row",
    alignItems: "center",
    alignSelf: "flex-end",
    gap: 4,
    backgroundColor: colors.card,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: colors.terracotta,
    paddingHorizontal: 8,
    paddingVertical: 4,
  },
  removeItemBtnText: {
    color: colors.terracotta,
    fontSize: 10,
    fontWeight: "700",
  },
  whyRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 10, paddingTop: 8, borderTopWidth: 1, borderTopColor: colors.line },
  whyIcon: { width: 22, height: 22, borderRadius: 6, backgroundColor: colors.paper, alignItems: "center", justifyContent: "center" },
  whyCopy: { flex: 1 },
  whyTitle: { color: colors.muted, fontSize: 10, fontWeight: "700" },
  whySubtitle: { color: colors.muted, fontSize: 9, marginTop: 1 },
  auditBox: { marginTop: 8, padding: 10, borderRadius: 12, backgroundColor: colors.paper, gap: 6, borderWidth: 1, borderColor: colors.line },
  primaryButton: { minHeight: 52, borderRadius: 16, backgroundColor: colors.terracotta, alignItems: "center", justifyContent: "center", flexDirection: "row", gap: 8, paddingHorizontal: 16, marginTop: 6 },
  primaryButtonDisabled: { backgroundColor: "#EAE5D9" },
  primaryButtonText: { color: colors.white, fontSize: 14, fontWeight: "800" },
  primaryButtonTextDisabled: { color: "#A8A294" },
  footerHint: { color: colors.muted, fontSize: 11, lineHeight: 15, fontWeight: "600", marginBottom: 6, textAlign: "center" },
  textButton: { minHeight: 42, alignItems: "center", justifyContent: "center", flexDirection: "row", gap: 6, paddingVertical: 10, marginTop: 4, alignSelf: "center", paddingHorizontal: 16, borderRadius: 12, borderWidth: 1, borderColor: colors.line, backgroundColor: colors.card },
  textButtonLabel: { color: colors.ink, fontSize: 11, fontWeight: "700" },
  mutedNote: { color: colors.muted, fontSize: 11, marginVertical: 6 },
  itemQuickActionBtnDanger: { borderColor: "#F7D0C5", backgroundColor: "#FDF0ED" },

  // + Tabağa Öğe Ekle Styles
  addPlateItemContainer: {
    marginVertical: 10,
  },
  addPlateItemHeroBtn: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: colors.card,
    borderRadius: 16,
    borderWidth: 1.5,
    borderStyle: "dashed",
    borderColor: colors.moss,
    paddingHorizontal: 16,
    paddingVertical: 14,
    gap: 12,
  },
  addPlateItemIconCircle: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: "#EDF3EE",
    alignItems: "center",
    justifyContent: "center",
  },
  addPlateItemCopy: {
    flex: 1,
  },
  addPlateItemTitle: {
    fontSize: 13,
    fontWeight: "800",
    color: colors.moss,
  },
  addPlateItemSubtitle: {
    fontSize: 11,
    color: colors.muted,
    marginTop: 2,
  },
  addPlateItemCard: {
    backgroundColor: colors.card,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.line,
    padding: 14,
    gap: 10,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.04,
    shadowRadius: 6,
    elevation: 2,
  },
  addPlateItemCardHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  addPlateItemHeaderLeft: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  addPlateItemCardTitle: {
    fontSize: 12,
    fontWeight: "800",
    color: colors.ink,
    letterSpacing: 0.3,
  },
  quickAddLabel: {
    fontSize: 10,
    fontWeight: "800",
    color: colors.muted,
    letterSpacing: 0.6,
  },
  quickAddChipsRow: {
    flexDirection: "row",
    gap: 6,
    paddingBottom: 4,
  },
  quickAddChip: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "#F4F3ED",
    borderWidth: 1,
    borderColor: "#E5E3D8",
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 10,
  },
  quickAddChipText: {
    fontSize: 11,
    fontWeight: "700",
    color: colors.ink,
  },
  addPlateItemInputRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginTop: 2,
  },
  addPlateItemInput: {
    flex: 1,
    minHeight: 40,
    backgroundColor: colors.paper,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: 10,
    paddingHorizontal: 12,
    fontSize: 12,
    color: colors.ink,
  },
  addPlateItemSubmitBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: colors.moss,
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: 10,
  },
  addPlateItemSubmitBtnText: {
    color: colors.white,
    fontSize: 12,
    fontWeight: "800",
  },
});
