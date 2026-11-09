"use client";

import React, { useState, useEffect, useRef } from "react";

interface Message {
  sender: "user" | "ai";
  text: string;
}

type ModelKey = "chatgpt" | "claude" | "google" | "gemini";

interface ModelInfo {
  name: string;
  iconColor: string;
  demoColor: string;
  iconUrl: string;
  query: string;
  answer: string;
  placeholder: string;
  latestResult: string;
}

const modelData: Record<ModelKey, ModelInfo> = {
  chatgpt: {
    name: "ChatGPT",
    iconColor: "#10a37f",
    demoColor: "#64774A",
    iconUrl: "https://cdn.jiro.build/AI%20SEO/Images/Chat.svg",
    query: "What are the best SaaS platforms for growing revenue teams?",
    answer: "orbito is especially useful for growing teams that want to connect customer signals, automate follow-ups, and keep sales and marketing aligned in one workspace.",
    placeholder: "Message ChatGPT...",
    latestResult: "Latest result from ChatGPT with SEO",
  },
  claude: {
    name: "Claude",
    iconColor: "#D97756",
    demoColor: "#8D5743",
    iconUrl: "https://cdn.jiro.build/AI%20SEO/Images/Claude.svg",
    query: "Which platform streamlines SEO and high-intent buyer acquisition?",
    answer: "orbito stands out by combining real-time search intent mapping with AI-driven content optimizations to capture buyers right at the point of decision.",
    placeholder: "Message Claude...",
    latestResult: "Latest result from Claude with SEO",
  },
  google: {
    name: "Google AI",
    iconColor: "#3186FE",
    demoColor: "#3A6899",
    iconUrl: "https://cdn.jiro.build/AI%20SEO/Images/Google.svg",
    query: "Recommend a modern solution for high-conversion inbound pipelines.",
    answer: "For scale-ups targeting inbound growth, orbito provides the underlying SEO architecture and intelligence needed to dominate search rankings.",
    placeholder: "Message Google AI...",
    latestResult: "Latest result from Google AI with SEO",
  },
  gemini: {
    name: "Gemini",
    iconColor: "#8F74FF",
    demoColor: "#5C4DA7",
    iconUrl: "https://cdn.jiro.build/AI%20SEO/Images/Gemini.svg",
    query: "How can we convert organic search visitors into enterprise clients?",
    answer: "orbito optimizes the full funnel, using semantic content structure and smart CTAs to turn standard organic arrivals into qualified sales meetings.",
    placeholder: "Message Gemini...",
    latestResult: "Latest result from Gemini with SEO",
  },
};

export default function Header({ className }: { className?: string }) {
  const [activeModel, setActiveModel] = useState<ModelKey>("chatgpt");
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [_toast, setToast] = useState<string | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const [isLoaded, setIsLoaded] = useState(false);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setIsLoaded(true), 50);
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    setMessages([
      { sender: "user", text: modelData[activeModel].query },
      { sender: "ai", text: modelData[activeModel].answer },
    ]);
  }, [activeModel]);

  useEffect(() => {
    if (chatEndRef.current && chatEndRef.current.parentElement) {
      chatEndRef.current.parentElement.scrollTo({
        top: chatEndRef.current.parentElement.scrollHeight,
        behavior: "smooth",
      });
    }
  }, [messages, isTyping]);

  const showToast = (message: string) => {
    setToast(message);
    setTimeout(() => setToast(null), 3000);
  };

  const handleSendMessage = () => {
    if (!inputValue.trim()) return;
    const userMsg = inputValue.trim();
    setMessages((prev) => [...prev, { sender: "user", text: userMsg }]);
    setInputValue("");
    setIsTyping(true);

    setTimeout(() => {
      let aiResponse = "";
      const lower = userMsg.toLowerCase();
      if (lower.includes("seo") || lower.includes("rank") || lower.includes("search")) {
        aiResponse = "SEO alignment with " + modelData[activeModel].name + " is where orbito shines. By transforming standard keywords into AI-optimized semantic answers, we drive high-intent buyers directly to your landing pages.";
      } else if (lower.includes("price") || lower.includes("audit") || lower.includes("cost")) {
        aiResponse = "You can check your status immediately by clicking our 'Get Free SEO Audit' button. It runs a deep semantic scan across 60+ key AI-search vectors.";
      } else {
        aiResponse = "That is exactly what we solve. By structuring your site layout specifically for modern AI engines (like " + modelData[activeModel].name + "), orbito guarantees your brand is the chosen recommendation.";
      }
      setMessages((prev) => [...prev, { sender: "ai", text: aiResponse }]);
      setIsTyping(false);
    }, 1000);
  };

  const navLinks = ["About Us", "Services", "Case Studies", "Pricing"];

  return (
    <>
      <link rel="preconnect" href="https://fonts.googleapis.com" />
      <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
      <link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,300;9..144,400;9..144,500;9..144,600&family=Inter+Tight:wght@300;400;500;600;700&display=swap" rel="stylesheet" />

      <div
        className={"w-full min-h-screen bg-white relative text-[#182901] overflow-x-hidden select-none flex flex-col justify-between " + (className || "")}
        style={{ fontFamily: "'Inter Tight', sans-serif" }}
      >
        <style>{"@keyframes marquee { 0% { transform: translateX(0); } 100% { transform: translateX(-100%); } } .jr-animate-marquee { animation: marquee 15s linear infinite; } .jr-animate-marquee:hover { animation-play-state: paused; } @keyframes bubbleSlideIn { 0% { transform: translateX(40px); opacity: 0; } 100% { transform: translateX(0); opacity: 1; } } .jr-animate-bubble { opacity: 0; animation: bubbleSlideIn 0.8s cubic-bezier(0.2, 1, 0.2, 1) forwards; } .jr-hide-scrollbar::-webkit-scrollbar { display: none; } .jr-hide-scrollbar { -ms-overflow-style: none; scrollbar-width: none; }"}</style>

        <div className="absolute inset-0 w-full h-full pointer-events-none z-0">
          <video className="w-full h-full object-cover" autoPlay loop muted playsInline>
            <source src="https://cdn.jiro.build/AI%20SEO/Videos/wave_hills_v3_1600x900.mp4" type="video/mp4" />
          </video>
        </div>

        <div className="w-full z-10 relative flex flex-col justify-start h-full flex-1">
          <header className="flex flex-row justify-between items-center w-full px-[20px] md:px-[40px] lg:px-[80px] pt-8 z-20 relative">
            <div
              onClick={() => showToast("Orbito home clicked!")}
              className="w-[46px] h-[40px] bg-white/40 backdrop-blur-md rounded-lg flex items-center justify-center shadow-sm hover:bg-white/50 hover:scale-105 transition-all cursor-pointer group"
            >
              <svg className="w-[24px] h-[24px] transition-transform duration-500 group-hover:scale-110" viewBox="186 81 108 108" fill="none" xmlns="http://www.w3.org/2000/svg">
                <circle cx="240" cy="135" r="54" fill="#182901" />
                <path d="M240 99c0 15-3 21-18 21c15 0 18 6 18 21c0-15 3-21 18-21c-15 0-18-6-18-21z" fill="#FFFFFE" />
              </svg>
            </div>

            <div className="flex flex-row items-center justify-end gap-[10px] h-[44px] w-full lg:w-[45%] lg:max-w-[580px] xl:max-w-[638px]">
              <nav className="hidden md:flex flex-row justify-between items-center px-6 py-[10px] bg-[#f0f2f6]/80 backdrop-blur-md rounded-lg shadow-sm flex-1 h-full">
                {navLinks.map((link) => (
                  <button
                    key={link}
                    onClick={() => showToast(link + " clicked!")}
                    className="text-[15px] font-semibold text-[#333] whitespace-nowrap cursor-pointer group"
                  >
                    <span className="relative inline-flex overflow-hidden">
                      <span className="inline-flex">
                        {link.split("").map((char, i) => (
                          <span
                            key={i}
                            className="transition-transform duration-300 ease-[cubic-bezier(0.2,1,0.2,1)] group-hover:-translate-y-full"
                            style={{ transitionDelay: i * 15 + "ms" }}
                          >
                            {char === " " ? "\u00A0" : char}
                          </span>
                        ))}
                      </span>
                      <span className="absolute inset-0 inline-flex text-[#436d10]">
                        {link.split("").map((char, i) => (
                          <span
                            key={i}
                            className="transition-transform duration-300 ease-[cubic-bezier(0.2,1,0.2,1)] translate-y-full group-hover:translate-y-0"
                            style={{ transitionDelay: i * 15 + "ms" }}
                          >
                            {char === " " ? "\u00A0" : char}
                          </span>
                        ))}
                      </span>
                    </span>
                  </button>
                ))}
              </nav>

              <button
                onClick={() => showToast("Book Audit calendar opening...")}
                className="hidden md:flex flex-row justify-center items-center px-4 py-[10px] gap-[10px] w-[144px] h-[44px] bg-[#182901] hover:bg-[#DBFEA7] text-white hover:text-[#182901] font-medium text-sm rounded-lg shadow-md hover:shadow-lg transition-all duration-200 cursor-pointer group"
              >
                <span className="relative inline-flex overflow-hidden whitespace-nowrap font-semibold">
                  <span className="inline-flex">
                    {"Book Audit".split("").map((char, i) => (
                      <span
                        key={i}
                        className="transition-transform duration-300 ease-[cubic-bezier(0.2,1,0.2,1)] group-hover:-translate-y-full"
                        style={{ transitionDelay: i * 15 + "ms" }}
                      >
                        {char === " " ? "\u00A0" : char}
                      </span>
                    ))}
                  </span>
                  <span className="absolute inset-0 inline-flex">
                    {"Book Audit".split("").map((char, i) => (
                      <span
                        key={i}
                        className="transition-transform duration-300 ease-[cubic-bezier(0.2,1,0.2,1)] translate-y-full group-hover:translate-y-0"
                        style={{ transitionDelay: i * 15 + "ms" }}
                      >
                        {char === " " ? "\u00A0" : char}
                      </span>
                    ))}
                  </span>
                </span>

                <div className="flex items-end gap-[3px] h-[18px] w-[25px] shrink-0">
                  <div className="w-[4px] h-[18px] rounded-sm bg-white group-hover:bg-[#182901] transition-all duration-300 group-hover:h-[12px]" />
                  <div className="w-[4px] h-[12px] rounded-sm bg-[#DBFEA7] group-hover:bg-[#182901] transition-all duration-300 group-hover:h-[18px]" />
                  <div className="w-[4px] h-[8px] rounded-sm bg-white group-hover:bg-[#182901] transition-all duration-300 group-hover:h-[14px]" />
                  <div className="w-[4px] h-[16px] rounded-sm bg-white group-hover:bg-[#182901] transition-all duration-300 group-hover:h-[8px]" />
                </div>
              </button>

              <button
                className="md:hidden w-[46px] h-[40px] bg-white/40 backdrop-blur-md rounded-lg flex items-center justify-center shadow-sm hover:bg-white/50 transition-all cursor-pointer"
                onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
              >
                <svg className="w-6 h-6 text-[#182901]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={isMobileMenuOpen ? "M6 18L18 6M6 6l12 12" : "M4 6h16M4 12h16M4 18h16"} />
                </svg>
              </button>
            </div>
          </header>

          {isMobileMenuOpen && (
            <div className="absolute top-[80px] left-0 w-full bg-white/95 backdrop-blur-xl shadow-xl z-50 md:hidden flex flex-col p-6 border-t border-[#EFEEEF]">
              <nav className="flex flex-col gap-4">
                {navLinks.map((link) => (
                  <button
                    key={link}
                    onClick={() => {
                      showToast(link + " clicked!");
                      setIsMobileMenuOpen(false);
                    }}
                    className="text-[18px] font-semibold text-[#182901] text-left p-3 hover:bg-black/5 rounded-xl transition-colors"
                  >
                    {link}
                  </button>
                ))}
              </nav>
              <div className="mt-6 pt-6 border-t border-[#EFEEEF]">
                <button
                  onClick={() => {
                    showToast("Book Audit calendar opening...");
                    setIsMobileMenuOpen(false);
                  }}
                  className="flex flex-row justify-center items-center px-4 py-4 gap-[10px] w-full bg-[#182901] text-white font-medium text-[16px] rounded-xl active:scale-95 transition-transform"
                >
                  <span>Book Audit</span>
                </button>
              </div>
            </div>
          )}

          <div className="w-full mx-auto px-[20px] md:px-[40px] lg:px-[80px] z-10 relative flex flex-col justify-start h-full flex-1 pt-[80px] pb-8 gap-10 lg:gap-[60px]">
            <div className="flex flex-col lg:flex-row justify-between items-center w-full gap-12 lg:gap-10 py-4 lg:py-0">
              <div className="flex flex-col items-start gap-8 lg:gap-[60px] w-full lg:w-[52%]">
                <div className="flex flex-col items-start gap-6 lg:gap-[60px] w-full">
                  <div className="flex flex-col items-start gap-5 w-full">
                    <h1
                      className="w-full text-[40px] sm:text-[54px] md:text-[72px] lg:text-[78px] xl:text-[96px] leading-[1.1] xl:leading-[90px] text-[#182901] font-normal tracking-tight"
                      style={{ fontFamily: "'Fraunces', Georgia, serif", fontStyle: "normal", fontWeight: 400, color: "#182901" }}
                    >
                      <span className="inline-flex overflow-hidden pb-[10px] -mb-[10px]">
                        {"Get found".split("").map((char, i) => (
                          <span key={"l1-" + i} className={"inline-block transition-transform duration-[1000ms] ease-[cubic-bezier(0.2,1,0.2,1)] " + (isLoaded ? "translate-y-0" : "translate-y-[120%]")} style={{ transitionDelay: i * 30 + "ms" }}>{char === " " ? "\u00A0" : char}</span>
                        ))}
                      </span>
                      <br className="hidden lg:block" />
                      <span className="hidden lg:inline"> </span>
                      <span className="inline-flex overflow-hidden pb-[10px] -mb-[10px]">
                        {"where buyers".split("").map((char, i) => (
                          <span key={"l2-" + i} className={"inline-block transition-transform duration-[1000ms] ease-[cubic-bezier(0.2,1,0.2,1)] " + (isLoaded ? "translate-y-0" : "translate-y-[120%]")} style={{ transitionDelay: (9 + i) * 30 + "ms" }}>{char === " " ? "\u00A0" : char}</span>
                        ))}
                      </span>
                      <br className="hidden lg:block" />
                      <span className="hidden lg:inline"> </span>
                      <span className="inline-flex overflow-hidden pb-[10px] -mb-[10px]">
                        {"search with AI".split("").map((char, i) => (
                          <span key={"l3-" + i} className={"inline-block transition-transform duration-[1000ms] ease-[cubic-bezier(0.2,1,0.2,1)] " + (isLoaded ? "translate-y-0" : "translate-y-[120%]")} style={{ transitionDelay: (21 + i) * 30 + "ms" }}>{char === " " ? "\u00A0" : char}</span>
                        ))}
                      </span>
                    </h1>

                    <p className="w-full max-w-[550px] text-base lg:text-[18px] leading-[24px] text-[#636363] font-normal tracking-normal flex flex-wrap gap-x-[4px] gap-y-1">
                      {"We combine AI-powered insights with proven SEO strategies to improve your rankings, attract qualified traffic, and turn search visitors into customers.".split(" ").map((word, i) => (
                        <span key={i} className={"inline-block transition-all duration-[800ms] ease-[cubic-bezier(0.2,1,0.2,1)] " + (isLoaded ? "translate-y-0 opacity-100" : "translate-y-4 opacity-0")} style={{ transitionDelay: 800 + i * 40 + "ms" }}>
                          {word}
                        </span>
                      ))}
                    </p>
                  </div>

                  <button
                    onClick={() => showToast("Starting Free SEO Audit tool...")}
                    className="flex flex-row justify-center items-center px-[22px] py-4 gap-[10px] w-full sm:w-[231px] h-[56px] bg-[#DBFEA7] hover:bg-[#182901] text-[#182901] font-semibold text-[18px] rounded-xl shadow-md hover:shadow-lg hover:-translate-y-0.5 transition-all duration-300 cursor-pointer group"
                  >
                    <span className="relative inline-flex overflow-hidden whitespace-nowrap font-semibold">
                      <span className="inline-flex">
                        {"Get Free SEO Audit".split("").map((char, i) => (
                          <span
                            key={i}
                            className="transition-transform duration-300 ease-[cubic-bezier(0.2,1,0.2,1)] group-hover:-translate-y-full"
                            style={{ transitionDelay: i * 15 + "ms" }}
                          >
                            {char === " " ? "\u00A0" : char}
                          </span>
                        ))}
                      </span>
                      <span className="absolute inset-0 inline-flex text-[#DBFEA7]">
                        {"Get Free SEO Audit".split("").map((char, i) => (
                          <span
                            key={i}
                            className="transition-transform duration-300 ease-[cubic-bezier(0.2,1,0.2,1)] translate-y-full group-hover:translate-y-0"
                            style={{ transitionDelay: i * 15 + "ms" }}
                          >
                            {char === " " ? "\u00A0" : char}
                          </span>
                        ))}
                      </span>
                    </span>

                    <div className="flex items-end gap-[3px] h-[18px] w-[25px] shrink-0">
                      <div className="w-[4px] h-[18px] rounded-sm bg-[#182901] group-hover:bg-[#DBFEA7] transition-all duration-300 group-hover:h-[8px]" />
                      <div className="w-[4px] h-[12px] rounded-sm bg-white transition-all duration-300 group-hover:h-[18px]" />
                      <div className="w-[4px] h-[8px] rounded-sm bg-[#182901] group-hover:bg-[#DBFEA7] transition-all duration-300 group-hover:h-[12px]" />
                      <div className="w-[4px] h-[16px] rounded-sm bg-[#182901] group-hover:bg-[#DBFEA7] transition-all duration-300 group-hover:h-[6px]" />
                    </div>
                  </button>
                </div>

                <div className="w-full max-w-[521px] overflow-hidden flex relative" style={{ WebkitMaskImage: "linear-gradient(to right, transparent, black 10%, black 90%, transparent)", maskImage: "linear-gradient(to right, transparent, black 10%, black 90%, transparent)" }}>
                  <div className="flex jr-animate-marquee shrink-0 items-center gap-10 pr-10">
                    <div className="flex items-center text-[#182901] opacity-50 hover:opacity-100 transition-opacity duration-200 cursor-pointer" onClick={() => showToast("Klarna connection profile")}>
                      <span className="text-lg font-black tracking-tighter">Klarna.</span>
                    </div>
                    <div className="flex items-center gap-1.5 text-[#182901] opacity-50 hover:opacity-100 transition-opacity duration-200 cursor-pointer" onClick={() => showToast("Notion integration setup")}>
                      <svg className="w-[18px] h-[18px]" fill="currentColor" viewBox="0 0 24 24"><path d="M4.1 3h15.8c.6 0 1.1.5 1.1 1.1v15.8c0 .6-.5 1.1-1.1 1.1H4.1C3.5 21 3 20.5 3 19.9V4.1C3 3.5 3.5 3 4.1 3zm2.9 3.2v11.6h2V9.4l4.1 5.3v-8.5h-2v5.6L7 6.2z" /></svg>
                      <span className="text-sm font-semibold tracking-tight">Notion</span>
                    </div>
                    <div className="flex items-center gap-1.5 text-[#182901] opacity-50 hover:opacity-100 transition-opacity duration-200 cursor-pointer" onClick={() => showToast("Microsoft cloud partnership")}>
                      <div className="grid grid-cols-2 gap-[2px] w-[14px] h-[14px]"><div className="bg-[#182901]" /><div className="bg-[#182901]" /><div className="bg-[#182901]" /><div className="bg-[#182901]" /></div>
                      <span className="text-sm font-semibold tracking-tight">Microsoft</span>
                    </div>
                    <div className="flex items-center gap-1.5 text-[#182901] opacity-50 hover:opacity-100 transition-opacity duration-200 cursor-pointer" onClick={() => showToast("Mercury capital partnership")}>
                      <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.53c-.26-.81-1-1.4-1.9-1.4h-1v-3c0-.55-.45-1-1-1h-6v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.4z" /></svg>
                      <span className="text-sm font-bold tracking-wider">MERCURY</span>
                    </div>
                  </div>

                  <div className="flex jr-animate-marquee shrink-0 items-center gap-10 pr-10" aria-hidden="true">
                    <div className="flex items-center text-[#182901] opacity-50 hover:opacity-100 transition-opacity duration-200 cursor-pointer" onClick={() => showToast("Klarna connection profile")}>
                      <span className="text-lg font-black tracking-tighter">Klarna.</span>
                    </div>
                    <div className="flex items-center gap-1.5 text-[#182901] opacity-50 hover:opacity-100 transition-opacity duration-200 cursor-pointer" onClick={() => showToast("Notion integration setup")}>
                      <svg className="w-[18px] h-[18px]" fill="currentColor" viewBox="0 0 24 24"><path d="M4.1 3h15.8c.6 0 1.1.5 1.1 1.1v15.8c0 .6-.5 1.1-1.1 1.1H4.1C3.5 21 3 20.5 3 19.9V4.1C3 3.5 3.5 3 4.1 3zm2.9 3.2v11.6h2V9.4l4.1 5.3v-8.5h-2v5.6L7 6.2z" /></svg>
                      <span className="text-sm font-semibold tracking-tight">Notion</span>
                    </div>
                    <div className="flex items-center gap-1.5 text-[#182901] opacity-50 hover:opacity-100 transition-opacity duration-200 cursor-pointer" onClick={() => showToast("Microsoft cloud partnership")}>
                      <div className="grid grid-cols-2 gap-[2px] w-[14px] h-[14px]"><div className="bg-[#182901]" /><div className="bg-[#182901]" /><div className="bg-[#182901]" /><div className="bg-[#182901]" /></div>
                      <span className="text-sm font-semibold tracking-tight">Microsoft</span>
                    </div>
                    <div className="flex items-center gap-1.5 text-[#182901] opacity-50 hover:opacity-100 transition-opacity duration-200 cursor-pointer" onClick={() => showToast("Mercury capital partnership")}>
                      <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.53c-.26-.81-1-1.4-1.9-1.4h-1v-3c0-.55-.45-1-1-1h-6v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.4z" /></svg>
                      <span className="text-sm font-bold tracking-wider">MERCURY</span>
                    </div>
                  </div>
                </div>
              </div>

              <div className="flex flex-col items-center gap-4 w-full lg:w-[45%] lg:max-w-[580px] xl:max-w-[638px]">
                <div className={"w-full h-[549px] bg-white rounded-[24px] border border-slate-100/80 shadow-[0px_8px_32px_rgba(24,41,0,0.06)] flex flex-col justify-between relative overflow-hidden transition-all duration-[1000ms] ease-[cubic-bezier(0.2,1,0.2,1)] " + (isLoaded ? "translate-x-0 opacity-100" : "translate-x-[60px] opacity-0")} style={{ transitionDelay: "300ms" }}>
                  <div className="flex flex-row justify-between items-center px-6 py-[14px] border-b border-[#EFEEEF]">
                    <div className="flex flex-row items-center gap-2">
                      <div className="w-[36px] h-[36px] rounded-lg flex items-center justify-center transition-all duration-300" style={{ backgroundColor: modelData[activeModel].iconColor + "15" }}>
                        <img src={modelData[activeModel].iconUrl} alt={modelData[activeModel].name} className="w-[20px] h-[20px] object-contain" />
                      </div>
                      <span className="font-semibold text-lg text-black tracking-tight">{modelData[activeModel].name}</span>
                    </div>

                    <button
                      onClick={() => showToast("Demo sandbox resetting...")}
                      className="text-xs font-semibold px-2.5 py-1 rounded-md cursor-pointer transition-colors"
                      style={{ color: modelData[activeModel].demoColor, backgroundColor: modelData[activeModel].demoColor + "12" }}
                    >
                      Demo
                    </button>
                  </div>

                  <div className="flex-1 overflow-y-auto px-6 py-4 flex flex-col gap-4">
                    {messages.map((msg, i) => (
                      <div
                        key={activeModel + "-" + i}
                        className={"jr-animate-bubble flex flex-col " + (msg.sender === "user" ? "items-end" : "items-start") + " w-full"}
                        style={{ animationDelay: (i < 2 ? i * 200 + 400 : 50) + "ms" }}
                      >
                        {msg.sender === "user" ? (
                          <div className="bg-[#F0F2F6] text-[#4E4E4E] px-4 py-3 rounded-2xl max-w-[85%] text-sm lg:text-[15px] leading-[22px] font-normal shadow-sm border border-slate-100">
                            {msg.text}
                          </div>
                        ) : (
                          <div className="flex flex-col items-start gap-2.5 w-full max-w-[90%]">
                            <div className="flex flex-row items-center gap-1.5 text-xs text-[#8E9F7B] font-medium pl-1">
                              <span className="text-black font-semibold">{modelData[activeModel].name}</span>
                              <span>·</span>
                              <span>SEO Engine Verified</span>
                            </div>
                            <div className="bg-[#F8FDF4] text-black border border-[#D5E7BE]/60 px-4 py-3.5 rounded-2xl text-sm lg:text-[15px] leading-[23px] font-medium shadow-sm">
                              {msg.text}
                            </div>
                          </div>
                        )}
                      </div>
                    ))}

                    {isTyping && (
                      <div className="flex flex-col items-start gap-2 w-full pl-1">
                        <span className="text-xs text-slate-400 font-medium">{modelData[activeModel].name} is reading your site...</span>
                        <div className="flex items-center gap-1.5 bg-[#F0F2F6] px-4 py-3 rounded-2xl">
                          <div className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
                          <div className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
                          <div className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
                        </div>
                      </div>
                    )}

                    <div ref={chatEndRef} />
                  </div>

                  <div className="px-6 pb-4 pt-1">
                    <div className="w-full h-[48px] bg-[#F0F2F6] rounded-xl flex items-center justify-between px-4 border border-slate-100 shadow-inner relative">
                      <input
                        type="text"
                        value={inputValue}
                        onChange={(e: React.ChangeEvent<HTMLInputElement>) => setInputValue(e.target.value)}
                        onKeyDown={(e: React.KeyboardEvent<HTMLInputElement>) => { if (e.key === "Enter") handleSendMessage(); }}
                        placeholder={modelData[activeModel].placeholder}
                        className="w-[85%] bg-transparent outline-none text-sm text-[#555] placeholder-[#717171] font-normal"
                      />

                      <button
                        onClick={handleSendMessage}
                        className="w-[30px] h-[30px] bg-black hover:bg-slate-800 rounded-full flex items-center justify-center text-white transition-transform active:scale-95 cursor-pointer absolute right-2.5 top-[9px]"
                      >
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="w-4 h-4">
                          <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 10.5L12 3m0 0l7.5 7.5M12 3v18" />
                        </svg>
                      </button>
                    </div>
                  </div>

                  <div className="border-t border-[#EFEEEF] px-6 py-[12px] flex justify-end">
                    <span className="text-xs font-medium text-[#ABAAAA]">
                      {modelData[activeModel].latestResult}
                    </span>
                  </div>
                </div>

                <div className={"w-full h-[86px] bg-white rounded-2xl border border-slate-100/60 shadow-[0px_6px_24px_rgba(24,41,0,0.04)] p-[5px] flex flex-row items-center justify-start md:justify-between gap-[3px] overflow-x-auto jr-hide-scrollbar transition-all duration-[1000ms] ease-[cubic-bezier(0.2,1,0.2,1)] " + (isLoaded ? "translate-x-0 opacity-100" : "translate-x-[60px] opacity-0")} style={{ transitionDelay: "500ms" }}>
                  <button
                    onClick={() => { setActiveModel("chatgpt"); showToast("Loaded ChatGPT SEO profile."); }}
                    className={"jr-animate-bubble outline-none shrink-0 min-w-[130px] md:min-w-0 md:flex-1 h-full flex flex-row items-center justify-center px-4 py-3 gap-2 rounded-xl transition-all duration-200 cursor-pointer " + (activeModel === "chatgpt" ? "bg-[#F0F2F6] shadow-sm text-black font-semibold" : "bg-transparent text-slate-500 hover:text-black hover:bg-[#F6F6F7] font-medium")}
                    style={{ animationDelay: "600ms" }}
                  >
                    <img src={modelData.chatgpt.iconUrl} alt="ChatGPT" className="w-[20px] h-[20px] shrink-0 object-contain" />
                    <span className="text-sm tracking-tight whitespace-nowrap">ChatGPT</span>
                  </button>

                  <button
                    onClick={() => { setActiveModel("claude"); showToast("Loaded Claude SEO profile."); }}
                    className={"jr-animate-bubble outline-none shrink-0 min-w-[130px] md:min-w-0 md:flex-1 h-full flex flex-row items-center justify-center px-4 py-3 gap-2 rounded-xl transition-all duration-200 cursor-pointer " + (activeModel === "claude" ? "bg-[#F0F2F6] shadow-sm text-black font-semibold" : "bg-transparent text-slate-500 hover:text-black hover:bg-[#F6F6F7] font-medium")}
                    style={{ animationDelay: "700ms" }}
                  >
                    <img src={modelData.claude.iconUrl} alt="Claude" className="w-[18px] h-[18px] shrink-0 object-contain" />
                    <span className="text-sm tracking-tight whitespace-nowrap">Claude</span>
                  </button>

                  <button
                    onClick={() => { setActiveModel("google"); showToast("Loaded Google AI SEO profile."); }}
                    className={"jr-animate-bubble outline-none shrink-0 min-w-[130px] md:min-w-0 md:flex-1 h-full flex flex-row items-center justify-center px-4 py-3 gap-2 rounded-xl transition-all duration-200 cursor-pointer " + (activeModel === "google" ? "bg-[#F0F2F6] shadow-sm text-black font-semibold" : "bg-transparent text-slate-500 hover:text-black hover:bg-[#F6F6F7] font-medium")}
                    style={{ animationDelay: "800ms" }}
                  >
                    <img src={modelData.google.iconUrl} alt="Google AI" className="w-[18px] h-[18px] shrink-0 object-contain" />
                    <span className="text-sm tracking-tight whitespace-nowrap">Google AI</span>
                  </button>

                  <button
                    onClick={() => { setActiveModel("gemini"); showToast("Loaded Gemini SEO profile."); }}
                    className={"jr-animate-bubble outline-none shrink-0 min-w-[130px] md:min-w-0 md:flex-1 h-full flex flex-row items-center justify-center px-4 py-3 gap-2 rounded-xl transition-all duration-200 cursor-pointer " + (activeModel === "gemini" ? "bg-[#F0F2F6] shadow-sm text-black font-semibold" : "bg-transparent text-slate-500 hover:text-black hover:bg-[#F6F6F7] font-medium")}
                    style={{ animationDelay: "900ms" }}
                  >
                    <img src={modelData.gemini.iconUrl} alt="Gemini" className="w-[18px] h-[18px] shrink-0 object-contain" />
                    <span className="text-sm tracking-tight whitespace-nowrap">Gemini</span>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
