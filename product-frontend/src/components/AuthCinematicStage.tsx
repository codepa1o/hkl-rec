import { AnimatePresence, motion } from "motion/react";
import { type ReactNode, useEffect, useRef } from "react";

export type AuthMode = "login" | "register";
export type AuthPhase =
  | "entering"
  | "idle"
  | "switching"
  | "submitting"
  | "error"
  | "success";

interface AuthCinematicStageProps {
  mode: AuthMode;
  phase: AuthPhase;
  reducedMotion: boolean;
  children: ReactNode;
}

const COPY = {
  login: {
    eyebrow: "NEWS · INTENT · CONTEXT",
    title: ["继续你的", "阅读脉络"],
    body: "让每一次搜索、停留与选择，逐渐形成真正属于你的新闻视野。",
    note: "你的兴趣会变化，推荐也应当如此。",
  },
  register: {
    eyebrow: "YOUR READING PROFILE",
    title: ["建立你的", "阅读坐标"],
    body: "从第一次选择开始，让兴趣、语境与时间共同塑造你的阅读档案。",
    note: "每一次选择，都是阅读世界的新坐标。",
  },
} as const;

const cinematicEase = [0.77, 0, 0.18, 1] as const;

export default function AuthCinematicStage({
  mode,
  phase,
  reducedMotion,
  children,
}: AuthCinematicStageProps) {
  const previousModeRef = useRef(mode);
  const modeChangedDuringSwitch = previousModeRef.current !== mode;
  const copy = COPY[mode];
  const isSwitching = phase === "switching";
  const isSuccess = phase === "success";
  const sceneState =
    reducedMotion || !isSwitching
      ? "active"
      : modeChangedDuringSwitch
        ? "entering"
        : "exiting";

  useEffect(() => {
    previousModeRef.current = mode;
  }, [mode]);

  const curtainAnimation = reducedMotion
    ? { opacity: 1 }
    : isSuccess
      ? { x: "-44%", scaleX: 4.9, rotate: 0 }
      : isSwitching
        ? {
            x: ["0%", "-44%", "0%"],
            scaleX: [1, 4.9, 1],
            rotate: [-8, 0, -8],
          }
        : phase === "submitting"
          ? { x: "-3%", scaleX: 1.08, rotate: -8 }
          : { x: "0%", scaleX: 1, rotate: -8 };
  const curtainTransition = reducedMotion
    ? { duration: 0 }
    : {
        duration: isSuccess ? 0.68 : isSwitching ? 0.7 : 0.55,
        ease: cinematicEase,
      };
  const contentMotion = reducedMotion
    ? {
        initial: false as const,
        animate: { opacity: 1 },
      }
    : {
        initial: { opacity: 0, y: 24, filter: "blur(8px)" },
        animate: { opacity: 1, y: 0, filter: "blur(0px)" },
      };
  const sceneAnimation =
    sceneState === "exiting" && !reducedMotion
      ? { opacity: 0, y: -18, filter: "blur(7px)" }
      : contentMotion.animate;
  const sceneDuration = reducedMotion ? 0 : sceneState === "exiting" ? 0.28 : 0.34;

  return (
    <main
      className="zr-auth-page"
      data-mode={mode}
      data-phase={phase}
      data-testid="auth-stage"
    >
      <div aria-hidden="true" className="zr-auth-grain" />
      <motion.div
        aria-hidden="true"
        animate={curtainAnimation}
        className="zr-auth-curtain zr-auth-curtain--back"
        initial={reducedMotion ? false : { x: "-150%", rotate: -8 }}
        transition={{ ...curtainTransition, delay: reducedMotion ? 0 : 0.04 }}
      />
      <motion.div
        aria-hidden="true"
        animate={curtainAnimation}
        className="zr-auth-curtain"
        initial={reducedMotion ? false : { x: "-165%", rotate: -8 }}
        transition={curtainTransition}
      />

      <a className="zr-auth-brand" href="/" aria-label="新闻意图推荐">
        <span className="zr-auth-brand__mark">N</span>
        <span>新闻意图推荐</span>
      </a>

      <section className="zr-auth-story" aria-label="产品介绍">
        <motion.div
          key={mode}
          {...contentMotion}
          animate={sceneAnimation}
          className="zr-auth-story__copy"
          data-scene-state={sceneState}
          transition={{ duration: sceneDuration, ease: cinematicEase }}
        >
          <p className="zr-auth-eyebrow">{copy.eyebrow}</p>
          <h1 aria-label={copy.title.join("")}>
            <span>{copy.title[0]}</span>
            <span>{copy.title[1]}</span>
          </h1>
          <p>{copy.body}</p>
        </motion.div>
        <p className="zr-auth-story__note">{copy.note}</p>
      </section>

      <section className="zr-auth-panel">
        <motion.div
          key={mode}
          {...contentMotion}
          animate={
            phase === "error" && !reducedMotion
              ? { opacity: 1, x: [0, -4, 4, 0], filter: "blur(0px)" }
              : sceneAnimation
          }
          className="zr-auth-form-wrap"
          data-scene-state={sceneState}
          transition={{
            duration: phase === "error" ? 0.24 : sceneDuration,
            ease: cinematicEase,
          }}
        >
          {children}
        </motion.div>
      </section>

      <AnimatePresence>
        {isSuccess && (
          <motion.div
            animate={{ clipPath: "inset(0 0 0 0)" }}
            className="zr-auth-success"
            exit={{ opacity: 0 }}
            initial={reducedMotion ? false : { clipPath: "inset(0 100% 0 0)" }}
            transition={{
              duration: reducedMotion ? 0 : 0.68,
              ease: cinematicEase,
            }}
          >
            <p role="status">
              <strong>阅读世界正在展开</strong>
              <span>正在进入你的个性化信息流…</span>
            </p>
          </motion.div>
        )}
      </AnimatePresence>
    </main>
  );
}
