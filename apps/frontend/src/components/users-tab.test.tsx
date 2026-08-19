import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { UsersTab } from "./users-tab";

describe("UsersTab", () => {
  it("exposes user creation and row actions", () => {
    const onCreateUser = vi.fn();
    const onSetCreateUserMode = vi.fn();
    const onToggleStatus = vi.fn();
    const onToggleAdmin = vi.fn();
    const onRemove = vi.fn();

    render(
      <UsersTab
        users={[{ id: 1, email: "admin@example.com", is_active: true, is_admin: true } as never]}
        usersError={null}
        createUserMode={false}
        newEmail=""
        newPassword=""
        actionBusy={false}
        onCreateUser={onCreateUser}
        onSetCreateUserMode={onSetCreateUserMode}
        onEmailChange={vi.fn()}
        onPasswordChange={vi.fn()}
        onToggleStatus={onToggleStatus}
        onToggleAdmin={onToggleAdmin}
        onRemove={onRemove}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Ajouter un utilisateur" }));
    expect(onSetCreateUserMode).toHaveBeenCalledWith(true);
    expect(screen.getByRole("button", { name: "Désactiver" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retirer admin" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Supprimer" })).toBeInTheDocument();
  });
});