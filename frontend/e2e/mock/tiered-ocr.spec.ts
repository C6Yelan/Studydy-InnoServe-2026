import { expect, test } from "@playwright/test";
import { materialId, runId, structureRevision, structureView, mockKnowledgeMapApi } from "../fixtures/knowledge-map";

test("image evidence stays usable while visual pages point back to the original image", async ({ page }) => {
  const view = structureView();
  view.concepts[0].claims[0].evidence[0].source = "tesseract";
  view.excluded_pages = [{ page_ref: `page:sha256:${"9".repeat(64)}`, page: 3,
    stage: "evidence", reason_code: "OCR_VISUAL_REVIEW_REQUIRED" }];
  view.status = { processing: "partial", quality: "needs_review", decision: "review", reason_codes: ["PAGES_EXCLUDED"] };
  await mockKnowledgeMapApi(page, view);
  await page.goto(`/materials/${materialId}/runs/${runId}/knowledge-structures/${encodeURIComponent(structureRevision)}`);
  await expect(page.getByRole("status").filter({ hasText: "第 3 頁需對照原圖" })).toBeVisible();
  await expect(page.getByRole("button", { name: "教材概念：Stack" })).toBeVisible();
});
