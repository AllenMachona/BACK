---
name: critic-review
description: Code quality and design review protocol. Ensures no layout overflow, strict UI visual hierarchy, responsive accessibility, and empirical verification.
---

# Critic & Quality Review Protocol

## Core Rules
1. **No Horizontal Overflow**: Verify every page on desktop (1440px), laptop (1024px), tablet (768px), and mobile (375px). No element may cause horizontal document scrolling.
2. **Visual Hierarchy & Spacing**: Elements must not be crowded. Maintain clear whitespace margins and padding.
3. **Empirical Verification**: Verify rendered HTML structure and CSS styles empirically before declaring completion.
