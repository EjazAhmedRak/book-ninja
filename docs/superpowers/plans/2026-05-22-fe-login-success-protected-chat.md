# FE Login + Login Success + Protected Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first frontend auth + routing slice with `/login`, `/login-success`, and token-protected `/chat`, including a welcome banner and seeded assistant message in an interactive local chat shell.

**Architecture:** The app will use `react-router-dom` for route-level flow, a small in-memory Zustand auth store as the guard source of truth, and a `ProtectedRoute` wrapper for `/chat`. UI is split into focused page/components (`LoginPage`, `LoginSuccessPage`, `ChatPage`, `WelcomeBanner`, `ChatWindow`) and validated with Vitest + Testing Library in `jsdom`.

**Tech Stack:** React 18, Vite 5, React Router DOM 6, Zustand, Vitest 2, Testing Library (`@testing-library/react`, `@testing-library/jest-dom`), jsdom.

---

## File Structure Map

### New files
- `apps/frontend/src/AppRouter.jsx`: Central route table.
- `apps/frontend/src/store/useAuthStore.js`: In-memory auth token store.
- `apps/frontend/src/components/ProtectedRoute.jsx`: Guard component for authenticated routes.
- `apps/frontend/src/pages/LoginPage.jsx`: Public login entry.
- `apps/frontend/src/pages/LoginSuccessPage.jsx`: Success flash with timed redirect.
- `apps/frontend/src/pages/ChatPage.jsx`: Protected post-login page composition.
- `apps/frontend/src/components/WelcomeBanner.jsx`: Welcome section above chat.
- `apps/frontend/src/components/ChatWindow.jsx`: Seeded assistant + local composer behavior.
- `apps/frontend/src/test/setup.js`: Jest-dom setup hooks.
- `apps/frontend/src/test/router-auth.test.jsx`: Route/auth behavior tests.
- `apps/frontend/src/test/login-success.test.jsx`: Success redirect behavior tests.
- `apps/frontend/src/test/chat-window.test.jsx`: Seeded and composer behavior tests.

### Modified files
- `apps/frontend/package.json`: dependencies/devDependencies and test scripts.
- `apps/frontend/src/main.jsx`: router bootstrap.

### Optional config file (if Vitest environment issues appear)
- `apps/frontend/vitest.config.js`: explicit `jsdom` test environment.

---

### Task 1: Test + Routing Dependencies Baseline

**Files:**
- Modify: `apps/frontend/package.json`
- Create: `apps/frontend/src/test/setup.js`

- [ ] **Step 1: Update frontend dependencies and scripts**

Edit `apps/frontend/package.json` to include:

```json
{
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview",
    "test": "vitest run --environment jsdom --setupFiles ./src/test/setup.js"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.28.0",
    "zustand": "^5.0.0"
  },
  "devDependencies": {
    "vite": "^5.4.10",
    "vitest": "^2.1.3",
    "jsdom": "^24.1.3",
    "@testing-library/react": "^16.1.0",
    "@testing-library/jest-dom": "^6.6.3"
  }
}
```

- [ ] **Step 2: Add test setup file for DOM assertions**

Create `apps/frontend/src/test/setup.js`:

```js
import '@testing-library/jest-dom/vitest'
```

- [ ] **Step 3: Install dependencies**

Run:

```bash
npm install --workspace apps/frontend
```

Expected:
- Lockfile updated
- Install completes without missing peer dependency errors

- [ ] **Step 4: Verify Vitest command boots in jsdom mode**

Run:

```bash
npm --workspace apps/frontend run test
```

Expected:
- Process starts Vitest successfully
- It may report `No test files found` at this stage (acceptable)

- [ ] **Step 5: Commit baseline dependency/tooling setup**

```bash
git add apps/frontend/package.json package-lock.json apps/frontend/src/test/setup.js
git commit -m "chore(frontend): add router/auth test dependencies and vitest jsdom setup"
```

---

### Task 2: Route Shell + Auth Guard (TDD)

**Files:**
- Create: `apps/frontend/src/test/router-auth.test.jsx`
- Create: `apps/frontend/src/store/useAuthStore.js`
- Create: `apps/frontend/src/components/ProtectedRoute.jsx`
- Create: `apps/frontend/src/AppRouter.jsx`
- Modify: `apps/frontend/src/main.jsx`
- Create: `apps/frontend/src/pages/LoginPage.jsx`
- Create: `apps/frontend/src/pages/ChatPage.jsx`

- [ ] **Step 1: Write failing route guard tests**

Create `apps/frontend/src/test/router-auth.test.jsx`:

```jsx
import React from 'react'
import { beforeEach, describe, expect, test } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import AppRouter from '../AppRouter'
import { useAuthStore } from '../store/useAuthStore'

describe('router auth guard', () => {
  beforeEach(() => {
    useAuthStore.setState({ token: null })
  })

  test('redirects /chat to /login when token is missing', async () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <AppRouter />
      </MemoryRouter>
    )

    expect(await screen.findByRole('heading', { name: /sign in to book ninja/i })).toBeInTheDocument()
  })

  test('renders chat page when token exists', async () => {
    useAuthStore.setState({ token: 'token-123' })

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <AppRouter />
      </MemoryRouter>
    )

    expect(await screen.findByRole('heading', { name: /welcome to book ninja/i })).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
npm --workspace apps/frontend run test -- src/test/router-auth.test.jsx
```

Expected:
- FAIL due to missing `AppRouter`, `useAuthStore`, or page components

- [ ] **Step 3: Implement minimal auth store, guard, routes, and bootstrap**

Create `apps/frontend/src/store/useAuthStore.js`:

```js
import { create } from 'zustand'

export const useAuthStore = create((set) => ({
  token: null,
  setToken: (token) => set({ token }),
  clearToken: () => set({ token: null }),
}))
```

Create `apps/frontend/src/components/ProtectedRoute.jsx`:

```jsx
import React from 'react'
import { Navigate } from 'react-router-dom'
import { useAuthStore } from '../store/useAuthStore'

export default function ProtectedRoute({ children }) {
  const token = useAuthStore((state) => state.token)

  if (!token) {
    return <Navigate to="/login" replace />
  }

  return children
}
```

Create `apps/frontend/src/pages/LoginPage.jsx`:

```jsx
import React from 'react'

export default function LoginPage() {
  return (
    <main>
      <h1>Sign in to Book Ninja</h1>
    </main>
  )
}
```

Create `apps/frontend/src/pages/ChatPage.jsx`:

```jsx
import React from 'react'

export default function ChatPage() {
  return (
    <main>
      <h1>Welcome to Book Ninja</h1>
    </main>
  )
}
```

Create `apps/frontend/src/AppRouter.jsx`:

```jsx
import React from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import ProtectedRoute from './components/ProtectedRoute'
import LoginPage from './pages/LoginPage'
import ChatPage from './pages/ChatPage'

export default function AppRouter() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/chat"
        element={
          <ProtectedRoute>
            <ChatPage />
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  )
}
```

Update `apps/frontend/src/main.jsx`:

```jsx
import React from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import AppRouter from './AppRouter'

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <AppRouter />
    </BrowserRouter>
  </React.StrictMode>
)
```

- [ ] **Step 4: Run route guard tests and verify pass**

Run:

```bash
npm --workspace apps/frontend run test -- src/test/router-auth.test.jsx
```

Expected:
- PASS: both guard scenarios

- [ ] **Step 5: Commit route/auth shell**

```bash
git add apps/frontend/src/main.jsx apps/frontend/src/AppRouter.jsx apps/frontend/src/store/useAuthStore.js apps/frontend/src/components/ProtectedRoute.jsx apps/frontend/src/pages/LoginPage.jsx apps/frontend/src/pages/ChatPage.jsx apps/frontend/src/test/router-auth.test.jsx
git commit -m "feat(frontend): add routed auth shell with protected chat route"
```

---

### Task 3: Login and Login-Success Transition (TDD)

**Files:**
- Create: `apps/frontend/src/pages/LoginSuccessPage.jsx`
- Modify: `apps/frontend/src/pages/LoginPage.jsx`
- Modify: `apps/frontend/src/AppRouter.jsx`
- Create: `apps/frontend/src/test/login-success.test.jsx`

- [ ] **Step 1: Write failing login flow tests**

Create `apps/frontend/src/test/login-success.test.jsx`:

```jsx
import React from 'react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import AppRouter from '../AppRouter'
import { useAuthStore } from '../store/useAuthStore'

describe('login success transition', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    useAuthStore.setState({ token: null })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  test('login action sets token and navigates to login-success', async () => {
    render(
      <MemoryRouter initialEntries={['/login']}>
        <AppRouter />
      </MemoryRouter>
    )

    fireEvent.click(screen.getByRole('button', { name: /continue with google/i }))

    expect(await screen.findByRole('heading', { name: /login successful/i })).toBeInTheDocument()
    expect(useAuthStore.getState().token).toBe('demo-token')
  })

  test('login-success auto-redirects to /chat', async () => {
    useAuthStore.setState({ token: 'demo-token' })

    render(
      <MemoryRouter initialEntries={['/login-success']}>
        <AppRouter />
      </MemoryRouter>
    )

    vi.advanceTimersByTime(1300)

    expect(await screen.findByRole('heading', { name: /welcome to book ninja/i })).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
npm --workspace apps/frontend run test -- src/test/login-success.test.jsx
```

Expected:
- FAIL because `/login-success` route/page and login action do not exist yet

- [ ] **Step 3: Implement login action and success redirect page**

Update `apps/frontend/src/pages/LoginPage.jsx`:

```jsx
import React from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../store/useAuthStore'

export default function LoginPage() {
  const navigate = useNavigate()
  const setToken = useAuthStore((state) => state.setToken)

  const handleLogin = () => {
    setToken('demo-token')
    navigate('/login-success')
  }

  return (
    <main style={{ padding: '2rem', maxWidth: 520, margin: '0 auto' }}>
      <h1>Sign in to Book Ninja</h1>
      <p>Continue to access your personalized book assistant.</p>
      <button type="button" onClick={handleLogin}>
        Continue with Google
      </button>
    </main>
  )
}
```

Create `apps/frontend/src/pages/LoginSuccessPage.jsx`:

```jsx
import React, { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'

export default function LoginSuccessPage() {
  const navigate = useNavigate()

  useEffect(() => {
    const timer = setTimeout(() => {
      navigate('/chat', { replace: true })
    }, 1200)

    return () => clearTimeout(timer)
  }, [navigate])

  return (
    <main style={{ padding: '2rem', textAlign: 'center' }}>
      <h1>Login successful</h1>
      <p>Preparing your Book Ninja chat...</p>
    </main>
  )
}
```

Update `apps/frontend/src/AppRouter.jsx`:

```jsx
import React from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import ProtectedRoute from './components/ProtectedRoute'
import LoginPage from './pages/LoginPage'
import LoginSuccessPage from './pages/LoginSuccessPage'
import ChatPage from './pages/ChatPage'

export default function AppRouter() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/login-success" element={<LoginSuccessPage />} />
      <Route
        path="/chat"
        element={
          <ProtectedRoute>
            <ChatPage />
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  )
}
```

- [ ] **Step 4: Run login transition tests and verify pass**

Run:

```bash
npm --workspace apps/frontend run test -- src/test/login-success.test.jsx
```

Expected:
- PASS: token set + route transition behavior works

- [ ] **Step 5: Commit login-success flow**

```bash
git add apps/frontend/src/pages/LoginPage.jsx apps/frontend/src/pages/LoginSuccessPage.jsx apps/frontend/src/AppRouter.jsx apps/frontend/src/test/login-success.test.jsx
git commit -m "feat(frontend): add login page and login-success transition flow"
```

---

### Task 4: Welcome Banner + Local Chat Window (TDD)

**Files:**
- Create: `apps/frontend/src/components/WelcomeBanner.jsx`
- Create: `apps/frontend/src/components/ChatWindow.jsx`
- Modify: `apps/frontend/src/pages/ChatPage.jsx`
- Create: `apps/frontend/src/test/chat-window.test.jsx`

- [ ] **Step 1: Write failing chat UI behavior tests**

Create `apps/frontend/src/test/chat-window.test.jsx`:

```jsx
import React from 'react'
import { describe, expect, test } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import ChatPage from '../pages/ChatPage'

describe('chat page shell', () => {
  test('renders welcome banner and seeded assistant message', () => {
    render(<ChatPage />)

    expect(screen.getByRole('heading', { name: /welcome to book ninja/i })).toBeInTheDocument()
    expect(
      screen.getByText(/i can help you search books, recommend titles, and find ebook, audiobook, or purchase options/i)
    ).toBeInTheDocument()
  })

  test('appends user message when input is non-empty', () => {
    render(<ChatPage />)

    fireEvent.change(screen.getByLabelText(/message input/i), {
      target: { value: 'Find me sci-fi books by Asimov' },
    })
    fireEvent.click(screen.getByRole('button', { name: /send/i }))

    expect(screen.getByText('Find me sci-fi books by Asimov')).toBeInTheDocument()
  })

  test('does not append empty messages', () => {
    render(<ChatPage />)

    fireEvent.change(screen.getByLabelText(/message input/i), {
      target: { value: '   ' },
    })
    fireEvent.click(screen.getByRole('button', { name: /send/i }))

    const userMessages = screen.queryAllByTestId('user-message')
    expect(userMessages).toHaveLength(0)
  })
})
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
npm --workspace apps/frontend run test -- src/test/chat-window.test.jsx
```

Expected:
- FAIL due to missing `WelcomeBanner` and `ChatWindow` implementation

- [ ] **Step 3: Implement banner, local chat window, and page composition**

Create `apps/frontend/src/components/WelcomeBanner.jsx`:

```jsx
import React from 'react'

export default function WelcomeBanner() {
  return (
    <section
      aria-label="Welcome banner"
      style={{
        background: 'linear-gradient(90deg, #dcfce7, #ecfeff)',
        border: '1px solid #86efac',
        borderRadius: '12px',
        padding: '1rem',
        marginBottom: '1rem',
      }}
    >
      <h1 style={{ margin: 0 }}>Welcome to Book Ninja</h1>
      <p style={{ margin: '0.5rem 0 0 0' }}>You are signed in. Start a chat to discover your next book.</p>
    </section>
  )
}
```

Create `apps/frontend/src/components/ChatWindow.jsx`:

```jsx
import React, { useMemo, useState } from 'react'

const MAX_PROMPT_LENGTH = 3000

function createMessage(role, content) {
  return {
    id: crypto.randomUUID(),
    role,
    content,
    timestamp: new Date().toISOString(),
  }
}

export default function ChatWindow() {
  const initialMessages = useMemo(
    () => [
      createMessage(
        'assistant',
        'I can help you search books, recommend titles, and find ebook, audiobook, or purchase options.'
      ),
    ],
    []
  )

  const [messages, setMessages] = useState(initialMessages)
  const [input, setInput] = useState('')

  const handleSend = () => {
    const trimmed = input.trim()
    if (!trimmed) {
      return
    }

    setMessages((prev) => [...prev, createMessage('user', trimmed)])
    setInput('')
  }

  return (
    <section aria-label="Chat window" style={{ border: '1px solid #d1d5db', borderRadius: '12px', padding: '1rem' }}>
      <div style={{ minHeight: '220px', marginBottom: '1rem' }}>
        {messages.map((message) => (
          <p
            key={message.id}
            data-testid={message.role === 'user' ? 'user-message' : 'assistant-message'}
            style={{ margin: '0.5rem 0' }}
          >
            <strong>{message.role === 'assistant' ? 'Assistant' : 'You'}:</strong> {message.content}
          </p>
        ))}
      </div>

      <label htmlFor="chat-input">Message input</label>
      <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem' }}>
        <input
          id="chat-input"
          aria-label="Message input"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          maxLength={MAX_PROMPT_LENGTH}
          placeholder="Ask about books, genres, or formats"
          style={{ flex: 1 }}
        />
        <button type="button" onClick={handleSend}>
          Send
        </button>
      </div>
    </section>
  )
}
```

Update `apps/frontend/src/pages/ChatPage.jsx`:

```jsx
import React from 'react'
import WelcomeBanner from '../components/WelcomeBanner'
import ChatWindow from '../components/ChatWindow'
import { useAuthStore } from '../store/useAuthStore'
import { useNavigate } from 'react-router-dom'

export default function ChatPage() {
  const navigate = useNavigate()
  const clearToken = useAuthStore((state) => state.clearToken)

  const handleLogout = () => {
    clearToken()
    navigate('/login', { replace: true })
  }

  return (
    <main style={{ maxWidth: 900, margin: '0 auto', padding: '1.5rem' }}>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '0.5rem' }}>
        <button type="button" onClick={handleLogout}>
          Logout
        </button>
      </div>
      <WelcomeBanner />
      <ChatWindow />
    </main>
  )
}
```

- [ ] **Step 4: Run chat behavior tests and verify pass**

Run:

```bash
npm --workspace apps/frontend run test -- src/test/chat-window.test.jsx
```

Expected:
- PASS for seeded message render and local composer behavior

- [ ] **Step 5: Commit welcome + local chat shell**

```bash
git add apps/frontend/src/components/WelcomeBanner.jsx apps/frontend/src/components/ChatWindow.jsx apps/frontend/src/pages/ChatPage.jsx apps/frontend/src/test/chat-window.test.jsx
git commit -m "feat(frontend): add welcome banner and local chat window shell"
```

---

### Task 5: End-to-End Guard/Flow Verification

**Files:**
- Modify: `apps/frontend/src/test/router-auth.test.jsx`

- [ ] **Step 1: Add logout and guard regression test**

Update `apps/frontend/src/test/router-auth.test.jsx` with:

```jsx
test('logout clears token and returns user to login page', async () => {
  useAuthStore.setState({ token: 'token-123' })

  render(
    <MemoryRouter initialEntries={['/chat']}>
      <AppRouter />
    </MemoryRouter>
  )

  fireEvent.click(await screen.findByRole('button', { name: /logout/i }))

  expect(await screen.findByRole('heading', { name: /sign in to book ninja/i })).toBeInTheDocument()
  expect(useAuthStore.getState().token).toBeNull()
})
```

Also ensure imports include `fireEvent`:

```jsx
import { fireEvent, render, screen } from '@testing-library/react'
```

- [ ] **Step 2: Run full frontend test suite**

Run:

```bash
npm --workspace apps/frontend run test
```

Expected:
- PASS for all frontend tests

- [ ] **Step 3: Run frontend production build**

Run:

```bash
npm --workspace apps/frontend run build
```

Expected:
- Vite build completes with no errors

- [ ] **Step 4: Manual route smoke check in dev server**

Run:

```bash
npm --workspace apps/frontend run dev
```

Manual checks:
- Visit `/login`, click login CTA, observe `/login-success` then `/chat`.
- Visit `/chat` directly in a new session, confirm redirect to `/login`.
- On `/chat`, send a local message and confirm render.
- Click `Logout`, confirm redirect to `/login`.

- [ ] **Step 5: Commit verification/test refinements**

```bash
git add apps/frontend/src/test/router-auth.test.jsx
git commit -m "test(frontend): add logout guard regression coverage"
```

---

## Spec Coverage Check

- Route flow `/login` -> `/login-success` -> `/chat`: covered by Task 3 and Task 5.
- `/chat` auth validation with in-memory token: covered by Task 2 tests + guard.
- Welcome banner above chat window: covered by Task 4 implementation and tests.
- Seeded assistant message with user options: covered by Task 4 implementation and tests.
- Interactive local input/send with empty-input rejection: covered by Task 4 tests.
- No backend coupling for this milestone: enforced across tasks (local-only chat logic).

## Execution Notes

- Keep each task self-contained and commit after each task.
- Do not add `localStorage` persistence in this slice.
- Do not wire `/chat` API or SSE in this slice.
- If `vitest` CLI flags change in installed version, move test config to `apps/frontend/vitest.config.js` with equivalent `test.environment = 'jsdom'` and `setupFiles`.
