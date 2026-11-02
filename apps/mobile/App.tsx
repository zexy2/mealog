import AsyncStorage from "@react-native-async-storage/async-storage";
import { CameraView, useCameraPermissions } from "expo-camera";
import * as ImagePicker from "expo-image-picker";
import { StatusBar } from "expo-status-bar";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { Alert, KeyboardAvoidingView, Platform, StyleSheet } from "react-native";
import { SafeAreaProvider, SafeAreaView } from "react-native-safe-area-context";

import { AnalysisState, ANALYSIS_STEPS } from "./components/AnalysisState";
import { Banner } from "./components/Banner";
import { BottomNav, Screen } from "./components/BottomNav";
import { ErrorState } from "./components/ErrorState";
import { AbstentionScreen } from "./screens/Abstention";
import { CaptureScreen } from "./screens/Capture";
import { DayScreen } from "./screens/Day";
import { ReviewScreen } from "./screens/Review";
import { correctMeal, isDemoMode, MealApiError, resolveFoodName, submitMeal } from "./src/api";
import { buildMealCorrections, removeSavedMeal } from "./src/corrections";
import { buildDemoMeal, initialDayMeals } from "./src/demoData";
import { demoInput, demoScenarioFor } from "./src/demoScenarios";
import { t } from "./src/strings";
import { Candidate, DemoScenario, MealLog, PendingCapture, UnverifiedNutritionEstimate } from "./src/types";

const PENDING_KEY = "@mealog/pending-capture";
const DAY_MEALS_KEY = "@mealog/day-meals";

function newIdempotencyKey() {
  return `meal-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

export default function App() {
  return (
    <SafeAreaProvider>
      <AppContent />
    </SafeAreaProvider>
  );
}

function AppContent() {
  const cameraRef = useRef<CameraView>(null);
  const [permission, requestPermission] = useCameraPermissions();
  const [screen, setScreen] = useState<Screen>("capture");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [analysisStep, setAnalysisStep] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingCapture | null>(null);
  const [meal, setMeal] = useState<MealLog | null>(null);



  const [dayMeals, setDayMeals] = useState<MealLog[]>(isDemoMode ? initialDayMeals : []);

  const [banner, setBanner] = useState<string | null>(null);
  const [expandedItem, setExpandedItem] = useState<number | null>(null);
  const [portionEdits, setPortionEdits] = useState<Record<number, number>>({});
  const [selectedCandidates, setSelectedCandidates] = useState<Record<number, string>>({});
  const [quantityEdits, setQuantityEdits] = useState<Record<number, number | null>>({});
  const [reviewingSavedMealKey, setReviewingSavedMealKey] = useState<string | null>(null);
  const [highlightedMealKey, setHighlightedMealKey] = useState<string | null>(null);
  const [capturedImageUri, setCapturedImageUri] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  // Plate form: the catalogue lookup is a network call, so it has its own state
  // rather than freezing the whole review screen.
  const [resolvingPlateItem, setResolvingPlateItem] = useState(false);
  const [plateItemNotFoundFor, setPlateItemNotFoundFor] = useState<string | null>(null);


  useEffect(() => {
    AsyncStorage.getItem(PENDING_KEY)
      .then((raw) => {
        if (raw) setPending(JSON.parse(raw) as PendingCapture);
      })
      .catch(() => undefined);

    if (!isDemoMode) {
      AsyncStorage.getItem(DAY_MEALS_KEY)
        .then((raw) => {
          if (raw) setDayMeals(JSON.parse(raw) as MealLog[]);
        })
        .catch(() => undefined);
    }
  }, []);

  useEffect(() => {
    if (screen === "capture" && permission && !permission.granted && !permission.canAskAgain) return;
    if (screen === "capture" && permission && !permission.granted) {
      requestPermission().catch(() => undefined);
    }
  }, [permission, requestPermission, screen]);

  useEffect(() => {
    if (!busy) return undefined;
    const timer = setInterval(() => {
      setAnalysisStep((step) => Math.min(step + 1, ANALYSIS_STEPS.length - 1));
    }, 720);
    return () => clearInterval(timer);
  }, [busy]);

  useEffect(() => {
    if (!banner) return undefined;
    const timer = setTimeout(() => setBanner(null), 3600);
    return () => clearTimeout(timer);
  }, [banner]);

  async function persistPending(next: PendingCapture) {
    setPending(next);
    await AsyncStorage.setItem(PENDING_KEY, JSON.stringify(next));
  }

  async function clearPending() {
    setPending(null);
    await AsyncStorage.removeItem(PENDING_KEY);
  }

  async function submit(source: Omit<PendingCapture, "idempotencyKey">, retryKey?: string, demoRetry = false) {
    if (source.photo?.uri) {
      setCapturedImageUri(source.photo.uri);
    } else if (source.text) {
      setCapturedImageUri(null);
    }
    const capture: PendingCapture = { ...source, idempotencyKey: retryKey ?? newIdempotencyKey() };
    setReviewingSavedMealKey(null);
    setMeal(null);
    setHighlightedMealKey(null);
    setError(null);
    setAnalysisStep(0);
    setBusy(true);

    await persistPending(capture);
    try {
      if (isDemoMode && demoScenarioFor(capture.text) === "empty") {
        await new Promise((resolve) => setTimeout(resolve, 850));
        await clearPending();
        setMeal(null);
        setDayMeals([]);
        setBusy(false);
        setScreen("day");
        return;
      }
      const result = await submitMeal(capture, { demoRetry });
      await clearPending();
      setMeal(result);
      setPortionEdits({});
      setSelectedCandidates({});
      setQuantityEdits({});
      setExpandedItem(result.items.length > 0 ? 0 : null);
      setBusy(false);
      const hasOnlyAbstainedItems = result.items.length === 1 && result.items[0]?.food_id === "ABSTAIN";
      if (result.action === "auto_accept" && !result.degraded) {
        upsertMeal(result);
        setReviewingSavedMealKey(result.idempotency_key);
        setHighlightedMealKey(result.idempotency_key);
        setBanner(t("mealAdded"));
        setScreen("day");
      } else if (result.action === "ask" && (result.items.length === 0 || hasOnlyAbstainedItems)) {
        setScreen("abstain");
      } else {
        setScreen("review");
      }
    } catch (caught) {
      setBusy(false);
      setScreen("capture");
      setError(caught instanceof MealApiError || isDemoMode && caught instanceof Error ? caught.message : t("uploadFailed"));
    }
  }

  async function capturePhoto() {
    if (!cameraRef.current) return;
    try {
      const picture = await cameraRef.current.takePictureAsync({ quality: 0.82 });
      if (picture?.uri) await submit({ photo: { uri: picture.uri, mimeType: "image/jpeg" } });
    } catch {
      setError(t("cameraCaptureFailed"));
    }
  }

  async function choosePhoto() {
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ["images"],
      quality: 0.82,
      allowsEditing: false,
    });
    if (!result.canceled && result.assets[0]?.uri) {
      await submit({ photo: { uri: result.assets[0].uri, mimeType: result.assets[0].mimeType } });
    }
  }

  function upsertMeal(next: MealLog) {
    setDayMeals((current) => {
      const existingIndex = current.findIndex((item) => item.idempotency_key === next.idempotency_key);
      const existing = existingIndex >= 0 ? current[existingIndex] : undefined;
      const saved = { ...next, createdAt: next.createdAt ?? existing?.createdAt ?? new Date().toISOString() };
      if (!isDemoMode) {
        const nextState = existingIndex < 0 ? [saved, ...current] : current.map((item, index) => (index === existingIndex ? saved : item));
        AsyncStorage.setItem(DAY_MEALS_KEY, JSON.stringify(nextState)).catch(() => undefined);
      }
      if (existingIndex < 0) return [saved, ...current];
      return current.map((item, index) => (index === existingIndex ? saved : item));
    });
  }

  function openSavedMeal(savedMeal: MealLog) {
    setMeal(savedMeal);
    setReviewingSavedMealKey(savedMeal.idempotency_key);
    setPortionEdits({});
    setSelectedCandidates({});
    setQuantityEdits({});
    setExpandedItem(null);
    setScreen("review");
  }

  function requestRemoveMeal(savedMeal: MealLog) {
    Alert.alert(
      t("removeMealTitle"),
      t("removeMealCopy"),
      [
        { text: t("cancel"), style: "cancel" },
        {
          text: t("removeMealConfirm"),
          style: "destructive",
          onPress: () => {
            setDayMeals((current) => {
              const updated = removeSavedMeal(current, savedMeal.idempotency_key);
              if (!isDemoMode) {
                AsyncStorage.setItem(DAY_MEALS_KEY, JSON.stringify(updated)).catch(() => undefined);
              }
              return updated;
            });
            setHighlightedMealKey((current) => current === savedMeal.idempotency_key ? null : current);
            setBanner(t("mealRemoved"));
          },
        },
      ],
    );
  }

  async function saveReview() {
    if (!meal) return;
    const hasUnansweredCountClarification = meal.items.some((item, index) => {
      const clarification = item.clarification ?? null;
      const hasQuantityEdit = Object.prototype.hasOwnProperty.call(quantityEdits, index);
      return clarification?.kind === "count" && !hasQuantityEdit && item.quantity === null;
    });
    if (hasUnansweredCountClarification) {
      setBanner(t("clarifyCountRequired"));
      return;
    }
    const wasSaved = reviewingSavedMealKey !== null;
    const corrections = buildMealCorrections(meal, portionEdits, selectedCandidates, quantityEdits);
    setSaving(true);
    try {
      const saved = corrections.length > 0 ? await correctMeal(meal, corrections) : meal;
      upsertMeal(saved);
      setMeal(saved);
      setPortionEdits({});
      setSelectedCandidates({});
      setQuantityEdits({});
      setReviewingSavedMealKey(null);
      setHighlightedMealKey(null);
      setBanner(wasSaved ? t("mealUpdated") : saved.action === "ask" ? t("savedQuestionOpen") : t("mealAdded"));
      setScreen("day");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("correctionFailed"));
    } finally {
      setSaving(false);
    }
  }

  function chooseCandidate(itemIndex: number, candidate: Candidate) {
    setSelectedCandidates((current) => ({ ...current, [itemIndex]: candidate.food_id }));
  }

  function retryPending() {
    if (!pending) return;
    const { idempotencyKey, ...source } = pending;
    void submit(source, idempotencyKey, true);
  }

  function runDemoScenario(scenario: DemoScenario) {
    setText("");
    void submit({ text: demoInput(scenario) });
  }

  function undoAutoAcceptedMeal(savedMeal: MealLog) {
    setDayMeals((current) => {
      const updated = removeSavedMeal(current, savedMeal.idempotency_key);
      if (!isDemoMode) {
        AsyncStorage.setItem(DAY_MEALS_KEY, JSON.stringify(updated)).catch(() => undefined);
      }
      return updated;
    });
    setMeal(null);
    setReviewingSavedMealKey(null);
    setHighlightedMealKey(null);
    setBanner(t("mealUndone"));
  }

  function handleSelectCandidateFromAbstain(candidate: Candidate, itemIndex: number) {
    if (!meal) return;
    const updatedItems = [...meal.items];
    if (updatedItems[itemIndex]) {
      updatedItems[itemIndex] = {
        ...updatedItems[itemIndex],
        food_id: candidate.food_id,
        confidence: candidate.score,
        candidates: updatedItems[itemIndex].candidates.length > 0 ? updatedItems[itemIndex].candidates : [candidate],
      };
    }
    const updatedMeal: MealLog = {
      ...meal,
      items: updatedItems,
      action: "review",
    };
    setMeal(updatedMeal);
    setSelectedCandidates((curr) => ({ ...curr, [itemIndex]: candidate.food_id }));
    setScreen("review");
  }

  function handleRemoveItem(itemIndex: number) {
    if (!meal) return;
    const remainingItems = meal.items.filter((_, idx) => idx !== itemIndex);
    if (remainingItems.length === 0) {
      setMeal(null);
      setScreen("capture");
      return;
    }
    const updatedMeal: MealLog = {
      ...meal,
      items: remainingItems,
    };
    setMeal(updatedMeal);
    setPortionEdits({});
    setSelectedCandidates({});
    setQuantityEdits({});
  }

  function acceptUnverifiedEstimate(itemIndex: number, estimate: UnverifiedNutritionEstimate) {
    if (!meal || !meal.items[itemIndex]) return;
    const candidate: Candidate = {
      food_id: "USER_CUSTOM",
      name: estimate.dish_name,
      score: 0,
    };
    const items = meal.items.map((item, index) => index === itemIndex ? {
      ...item,
      query: estimate.dish_name,
      food_id: "USER_CUSTOM",
      candidates: [...item.candidates, candidate],
      grams: 0,
      grams_p10: 0,
      grams_p90: 0,
      nutrients: {
        kcal: estimate.kcal.midpoint,
        protein_g: estimate.protein_g.midpoint,
        carb_g: estimate.carb_g.midpoint,
        fat_g: estimate.fat_g.midpoint,
      },
      source_database: "Gemini — doğrulanmamış tahmin",
      portion_source: "llm_unverified_estimate",
      portion_provenance: "llm_unverified_estimate",
      nutrition_estimate: estimate,
      clarification: null,
    } : item);
    const totals = items.reduce((sum, item) => ({
      kcal: sum.kcal + item.nutrients.kcal,
      protein_g: sum.protein_g + item.nutrients.protein_g,
      carb_g: sum.carb_g + item.nutrients.carb_g,
      fat_g: sum.fat_g + item.nutrients.fat_g,
    }), { kcal: 0, protein_g: 0, carb_g: 0, fat_g: 0 });
    setMeal({ ...meal, action: "review", items, totals });
    setSelectedCandidates((current) => {
      const next = { ...current };
      delete next[itemIndex];
      return next;
    });
    setBanner("Doğrulanmamış AI tahmini incelemeye eklendi.");
    setScreen("review");
  }

  /**
   * The abstention screen's "name it instead" escape hatch. Same rule as
   * adding to a plate: the catalogue resolves the name, or the answer is no.
   */
  async function handleConfirmObservedFood(foodName: string) {
    if (!meal) return;
    const clean = foodName.trim();
    if (!clean) return;

    let resolution: Awaited<ReturnType<typeof resolveFoodName>>;
    try {
      resolution = await resolveFoodName(clean, "tr");
    } catch (error) {
      Alert.alert(
        "Katalog sorgulanamadı",
        error instanceof Error && error.message ? error.message : "Lütfen yeniden deneyin.",
      );
      return;
    }

    if (resolution.action === "abstain" || resolution.food_id === "ABSTAIN") {
      Alert.alert(
        "Katalogda Bulunamadı",
        `"${clean}" yemek kataloğunda yok. Adı değiştirin, bir öneri isteyin ya da kaloriyi kendiniz girin.`,
      );
      return;
    }

    const name = resolution.name ?? clean;
    const item: MealLog["items"][number] = {
      query: clean,
      food_id: resolution.food_id,
      candidates: resolution.candidates.length > 0
        ? resolution.candidates
        : [{ food_id: resolution.food_id, name, score: 1 }],
      grams: resolution.grams,
      grams_p10: resolution.grams_p10,
      grams_p90: resolution.grams_p90,
      confidence: resolution.confidence,
      nutrients: resolution.nutrients,
      source_database: resolution.source_database ?? undefined,
      portion_source: resolution.portion_source,
      portion_provenance: resolution.portion_provenance,
    };

    const items = [...meal.items, item];
    const totals = items.reduce((sum, it) => ({
      kcal: sum.kcal + it.nutrients.kcal,
      protein_g: Math.round((sum.protein_g + it.nutrients.protein_g) * 10) / 10,
      carb_g: Math.round((sum.carb_g + it.nutrients.carb_g) * 10) / 10,
      fat_g: Math.round((sum.fat_g + it.nutrients.fat_g) * 10) / 10,
    }), { kcal: 0, protein_g: 0, carb_g: 0, fat_g: 0 });
    setMeal({ ...meal, action: "review", items, totals, question: null });
    setScreen("review");
    setBanner(`"${name}" öğüne eklendi.`);
  }

  /**
   * Add a typed food to the plate.
   *
   * The client does not know what "simit" is, and must not pretend to (D1):
   * the catalogue decides. A name the catalogue cannot resolve becomes an
   * abstention card, and the user's own calorie number is the only other way
   * in — clearly labelled as their input, never as catalogue nutrition.
   */
  function saveUncaloriedNote(abstainMeal: MealLog, dishName: string) {
    const noteMeal: MealLog = {
      ...abstainMeal,
      action: "review",
      items: [
        {
          query: dishName,
          food_id: "ABSTAIN",
          candidates: [],
          grams: 0,
          grams_p10: 0,
          grams_p90: 0,
          confidence: 1.0,
          nutrients: { kcal: 0, protein_g: 0, carb_g: 0, fat_g: 0 },
          portion_provenance: "uncaloried_note",
          source_database: "Kullanıcı Notu",
          portion_source: "uncaloried_note",
        },
      ],
      totals: { kcal: 0, protein_g: 0, carb_g: 0, fat_g: 0 },
    };
    upsertMeal(noteMeal);
    setHighlightedMealKey(noteMeal.idempotency_key);
    setBanner("Öğün kalorisiz not olarak günlüğe eklendi.");
    setMeal(null);
    setScreen("day");
  }

  function saveManualCalories(abstainMeal: MealLog, dishName: string, calories: number) {
    const manualMeal: MealLog = {
      ...abstainMeal,
      action: "review",
      items: [
        {
          query: dishName,
          food_id: "USER_CUSTOM",
          candidates: [],
          grams: 0,
          grams_p10: 0,
          grams_p90: 0,
          confidence: 1.0,
          nutrients: { kcal: calories, protein_g: 0, carb_g: 0, fat_g: 0 },
          portion_provenance: "manual_user_input",
          source_database: "Kullanıcı Girişi",
          portion_source: "manual_user_input",
        },
      ],
      totals: { kcal: calories, protein_g: 0, carb_g: 0, fat_g: 0 },
    };
    upsertMeal(manualMeal);
    setHighlightedMealKey(manualMeal.idempotency_key);
    setBanner(`Öğün ${calories} kcal manuel kullanıcı girişi olarak kaydedildi.`);
    setMeal(null);
    setScreen("day");
  }

  async function handleAddItemToPlate(
    foodName: string,
    customKcal?: number,
    confirmedFoodId?: string,
  ): Promise<boolean> {
    if (!meal) return false;
    const clean = foodName.trim();
    if (!clean) return false;

    if (customKcal !== undefined) {
      if (!Number.isFinite(customKcal) || customKcal <= 0 || customKcal > 5000) {
        Alert.alert("Geçersiz kalori", "1–5000 arası bir kalori değeri girin.");
        return false;
      }
      return addResolvedItem({
        query: clean,
        food_id: "USER_CUSTOM",
        candidates: [{ food_id: "USER_CUSTOM", name: clean, score: 1 }],
        grams: 0,
        grams_p10: 0,
        grams_p90: 0,
        confidence: 1,
        nutrients: { kcal: customKcal, protein_g: 0, carb_g: 0, fat_g: 0 },
        portion_provenance: "manual_user_input",
        portion_source: "manual_user_input",
        source_database: "Kullanıcı Girişi",
      }, `"${clean}" ${customKcal} kcal manuel giriş olarak eklendi.`);
      return Promise.resolve(true);
    }

    let resolution: Awaited<ReturnType<typeof resolveFoodName>>;
    try {
      setResolvingPlateItem(true);
      resolution = await resolveFoodName(clean, "tr");
    } catch (error) {
      Alert.alert(
        "Katalog sorgulanamadı",
        error instanceof Error && error.message ? error.message : "Lütfen yeniden deneyin.",
      );
      return false;
    } finally {
      setResolvingPlateItem(false);
    }

    if (resolution.action === "abstain" || resolution.food_id === "ABSTAIN") {
      // Not a near-miss. The plate form shows the manual-entry branch instead
      // of inventing a row the catalogue does not have.
      setPlateItemNotFoundFor(clean);
      return false;
    }

    const chosen = confirmedFoodId ?? resolution.food_id;
    const chosenName = resolution.candidates.find((c) => c.food_id === chosen)?.name
      ?? resolution.name
      ?? clean;

    addResolvedItem({
      query: clean,
      food_id: chosen,
      candidates: resolution.candidates.length > 0
        ? resolution.candidates
        : [{ food_id: chosen, name: chosenName, score: 1 }],
      grams: resolution.grams,
      grams_p10: resolution.grams_p10,
      grams_p90: resolution.grams_p90,
      confidence: resolution.confidence,
      nutrients: resolution.nutrients,
      portion_provenance: resolution.portion_provenance,
      portion_source: resolution.portion_source,
      source_database: resolution.source_database ?? undefined,
      unit: "porsiyon",
      quantity: 1,
    }, `"${chosenName}" tabağa eklendi.`);
    return true;
  }

  function addResolvedItem(item: MealLog["items"][number], message: string): boolean {
    if (!meal) return false;
    const newItems = [...meal.items, item];
    const newTotals = {
      kcal: newItems.reduce((sum, it) => sum + (it.nutrients?.kcal || 0), 0),
      protein_g: Math.round(newItems.reduce((sum, it) => sum + (it.nutrients?.protein_g || 0), 0) * 10) / 10,
      carb_g: Math.round(newItems.reduce((sum, it) => sum + (it.nutrients?.carb_g || 0), 0) * 10) / 10,
      fat_g: Math.round(newItems.reduce((sum, it) => sum + (it.nutrients?.fat_g || 0), 0) * 10) / 10,
    };
    setMeal({ ...meal, items: newItems, totals: newTotals });
    setBanner(message);
    return true;
  }

  function suggestDishToQueue(dishName: string) {
    Alert.alert(
      "Öneri Bildirildi (UI Prototipi)",
      `"${dishName}" önerisi arayüz prototipinde işaretlendi. Production mimarisinde bu talep, kullanıcı onayıyla anonimleştirilmiş katalog geri bildirim kuyruğuna aktarılır.`,
    );
  }

  function leaveAbstention() {
    setMeal(null);
    setText("");
    setScreen("capture");
  }

  const totalCalories = useMemo(() => dayMeals.reduce((sum, item) => sum + item.totals.kcal, 0), [dayMeals]);
  const totalProtein = useMemo(() => dayMeals.reduce((sum, item) => sum + item.totals.protein_g, 0), [dayMeals]);
  const totalCarbs = useMemo(() => dayMeals.reduce((sum, item) => sum + (item.totals.carb_g ?? 0), 0), [dayMeals]);
  const totalFat = useMemo(() => dayMeals.reduce((sum, item) => sum + (item.totals.fat_g ?? 0), 0), [dayMeals]);

  if (busy) {
    return <AppShell><AnalysisState step={analysisStep} imageUri={capturedImageUri} /></AppShell>;
  }

  if (error) {
    return (
      <AppShell>
        <ErrorState message={error} canRetry={Boolean(pending)} onRetry={retryPending} onRetake={() => { setError(null); setScreen("capture"); }} />
        <BottomNav screen="capture" canReview={false} onChange={setScreen} />
      </AppShell>
    );
  }

  return (
    <AppShell>
      {banner ? <Banner message={banner} /> : null}
      {screen === "capture" ? (
        <CaptureScreen
          cameraRef={cameraRef}
          permissionGranted={permission?.granted ?? false}
          requestPermission={requestPermission}
          text={text}
          setText={setText}
          pending={pending}
          onCapture={capturePhoto}
          onChoosePhoto={choosePhoto}
          onSubmitText={() => submit({ text: text.trim() || "plate" })}
          onRetry={retryPending}
          onDemoScenario={runDemoScenario}
        />
      ) : null}
      {screen === "abstain" && meal ? (
        <AbstentionScreen
          meal={meal}
          imageUri={capturedImageUri}
          onConfirmObserved={handleConfirmObservedFood}
          onSelectCandidateDirectly={handleSelectCandidateFromAbstain}
          onDescribe={leaveAbstention}
          onRetake={leaveAbstention}
          onSaveUncaloriedNote={saveUncaloriedNote}
          onSaveManualCalories={saveManualCalories}
          onAcceptEstimate={(estimate) => acceptUnverifiedEstimate(0, estimate)}
          onSuggestDish={suggestDishToQueue}
        />
      ) : null}


      {screen === "review" && meal ? (
        <ReviewScreen
          meal={meal}
          imageUri={capturedImageUri}
          expandedItem={expandedItem}
          setExpandedItem={setExpandedItem}

          portionEdits={portionEdits}
          setPortionEdits={setPortionEdits}
          quantityEdits={quantityEdits}
          setQuantityEdits={setQuantityEdits}
          selectedCandidates={selectedCandidates}
          onChooseCandidate={chooseCandidate}
          onRemoveItem={handleRemoveItem}
          onAddItem={handleAddItemToPlate}
          onAcceptEstimate={acceptUnverifiedEstimate}
          onSave={saveReview}
          isSaved={reviewingSavedMealKey !== null}
          saving={saving}
          onBack={() => {
            if (reviewingSavedMealKey) {
              setReviewingSavedMealKey(null);
              setMeal(null);
              setScreen("day");
              return;
            }
            setMeal(null);
            setScreen("capture");
          }}
        />
      ) : null}
      {screen === "day" ? (
        <DayScreen
          meals={dayMeals}
          totalCalories={totalCalories}
          totalProtein={totalProtein}
          totalCarbs={totalCarbs}
          totalFat={totalFat}
          highlightedMealKey={highlightedMealKey}
          onCapture={() => setScreen("capture")}
          onOpenMeal={openSavedMeal}
          onRemoveMeal={requestRemoveMeal}
          onUndoMeal={undoAutoAcceptedMeal}
        />
      ) : null}
      <BottomNav
        screen={screen}
        onChange={(next) => {
          if (next === "review" && !meal) {
            if (dayMeals.length > 0) {
              openSavedMeal(dayMeals[0]);
            } else {
              Alert.alert(t("navReview"), "Henüz analiz edilmiş bir öğün yok. Lütfen bir yemek fotoğrafı çekin veya yemek adı girin.");
              setScreen("capture");
            }
            return;
          }
          setScreen(next);
        }}
      />
    </AppShell>
  );
}

function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <SafeAreaView style={styles.root}>
      <KeyboardAvoidingView style={styles.root} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <StatusBar style="dark" />
        {children}
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#F4F1EA" },
});
