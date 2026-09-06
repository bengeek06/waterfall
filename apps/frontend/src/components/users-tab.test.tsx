import type { FormEvent } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { UsersTab, type UsersTabProps } from "./users-tab";
import type { AuthUserAdmin } from "@/lib/backend";

afterEach(() => cleanup());

const user = (overrides: Partial<AuthUserAdmin>): AuthUserAdmin =>
  ({
    id: 1,
    email: "alice@example.com",
    is_active: true,
    is_admin: false,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    ...overrides,
  }) as AuthUserAdmin;

function renderTab(overrides: Partial<UsersTabProps> = {}) {
  const props: UsersTabProps = {
    items: [user({})],
    pagination: { total: 1, limit: 20, offset: 0 },
    onPaginationChange: vi.fn(),
    sort: null,
    onSortChange: vi.fn(),
    search: "",
    onSearchChange: vi.fn(),
    isLoading: false,
    isActionPending: false,
    usersError: null,
    createUserMode: false,
    newEmail: "",
    newPassword: "",
    actionBusy: false,
    onCreateUser: (event) => event.preventDefault(),
    onSetCreateUserMode: vi.fn(),
    onEmailChange: vi.fn(),
    onPasswordChange: vi.fn(),
    onToggleStatus: vi.fn(),
    onToggleAdmin: vi.fn(),
    onRemove: vi.fn(),
    ...overrides,
  };
  return render(<UsersTab {...props} />);
}

describe("UsersTab", () => {
  it("renders an active, non-admin user with the expected badges and actions", () => {
    renderTab({ items: [user({ email: "alice@example.com", is_active: true, is_admin: false })] });
    expect(screen.getByText("alice@example.com")).toBeInTheDocument();
    expect(screen.getByText("Actif")).toBeInTheDocument();
    expect(screen.getByText("Standard")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Désactiver" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Promouvoir admin" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Supprimer" })).toBeInTheDocument();
  });

  it("renders an inactive admin user with the opposite badges and action labels", () => {
    renderTab({ items: [user({ is_active: false, is_admin: true })] });
    expect(screen.getByText("Inactif")).toBeInTheDocument();
    expect(screen.getByText("Admin")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Activer" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retirer admin" })).toBeInTheDocument();
  });

  it("calls onSortChange with the server column name when the Email header is clicked", () => {
    const onSortChange = vi.fn();
    renderTab({ onSortChange });
    fireEvent.click(screen.getByRole("button", { name: "Email" }));
    expect(onSortChange).toHaveBeenCalledExactlyOnceWith("email");
  });

  it("calls the corresponding callback with the exact user row when an action button is clicked", () => {
    const onToggleStatus = vi.fn();
    const onToggleAdmin = vi.fn();
    const onRemove = vi.fn();
    const target = user({ id: 42, email: "target@example.com" });
    renderTab({ items: [target], onToggleStatus, onToggleAdmin, onRemove });

    fireEvent.click(screen.getByRole("button", { name: "Désactiver" }));
    fireEvent.click(screen.getByRole("button", { name: "Promouvoir admin" }));
    fireEvent.click(screen.getByRole("button", { name: "Supprimer" }));

    expect(onToggleStatus).toHaveBeenCalledExactlyOnceWith(target);
    expect(onToggleAdmin).toHaveBeenCalledExactlyOnceWith(target);
    expect(onRemove).toHaveBeenCalledExactlyOnceWith(target);
  });

  it("disables every row action while an action is busy", () => {
    renderTab({ actionBusy: true });
    expect(screen.getByRole("button", { name: "Désactiver" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Promouvoir admin" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Supprimer" })).toBeDisabled();
  });

  it("freezes the DataTable (search and pagination) and disables row actions while a confirmation is pending", () => {
    renderTab({
      isActionPending: true,
      pagination: { total: 40, limit: 20, offset: 20 },
    });
    expect(screen.getByLabelText("Rechercher un utilisateur")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Précédent" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Suivant" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Désactiver" })).toBeDisabled();
  });

  it("shows the users error alert outside the create dialog when not creating a user", () => {
    renderTab({ usersError: "Liste des utilisateurs indisponible.", createUserMode: false });
    expect(screen.getByText("Liste des utilisateurs indisponible.")).toBeInTheDocument();
  });

  it("shows the users error alert inside the create dialog when creating a user", () => {
    renderTab({ usersError: "Email déjà utilisé.", createUserMode: true });
    expect(screen.getByText("Email déjà utilisé.")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("opens the create dialog when clicking the add-user button", () => {
    const onSetCreateUserMode = vi.fn();
    renderTab({ onSetCreateUserMode });
    fireEvent.click(screen.getByRole("button", { name: "Ajouter un utilisateur" }));
    expect(onSetCreateUserMode).toHaveBeenCalledExactlyOnceWith(true);
  });

  it("submits the create form through the wrapping form's onCreateUser callback", () => {
    const onCreateUser = vi.fn((event: FormEvent) => event.preventDefault());
    renderTab({ onCreateUser, createUserMode: true, newEmail: "new@example.com", newPassword: "password123" });
    fireEvent.click(screen.getByRole("button", { name: "Créer" }));
    expect(onCreateUser).toHaveBeenCalledTimes(1);
  });
});
