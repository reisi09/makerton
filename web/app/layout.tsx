import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ICE-ZERO 사거리 제설",
  description: "사거리 모형 사진에서 도로 위 눈을 찾고, 북동쪽 제설 기지에서 가장 빠른 경로로 제설차를 출동시킵니다.",
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
