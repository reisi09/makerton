import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ICE-ZERO 사거리 제설",
  description: "수원 119 결빙 예측 모델이 2025년 겨울밤에 판단하고 제설차를 출동시키는 모습을 재생한다",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <head>
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable.min.css" />
      </head>
      <body>{children}</body>
    </html>
  );
}
