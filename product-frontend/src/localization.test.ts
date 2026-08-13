import { describe, expect, it } from "vitest";
import {
  localizeCategoryName,
  localizePersonaName,
  localizeProfileSeedName,
  localizeRecommendationReason,
} from "./localization";

describe("动态界面文案中文化", () => {
  it("翻译已知分类和用户画像，未知值保留原文", () => {
    expect(localizeCategoryName("Finance")).toBe("财经");
    expect(localizeCategoryName("football")).toBe("足球");
    expect(localizePersonaName("Autos Reader")).toBe("汽车读者");
    expect(localizeProfileSeedName("cold_start_default")).toBe("默认冷启动");
    expect(localizeCategoryName("Unmapped Topic")).toBe("Unmapped Topic");
  });

  it("翻译后端返回的推荐原因", () => {
    expect(
      localizeRecommendationReason(
        "Selected because recent query categories boosted this article.",
      ),
    ).toBe("近期搜索的相关分类提升了这篇文章的推荐优先级。");
  });
});
