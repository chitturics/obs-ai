"""Tests for SCIM 2.0 user provisioning."""

import pytest


@pytest.fixture
def store(tmp_path, monkeypatch):
    import chat_app.scim as scim_mod
    monkeypatch.setattr(scim_mod, "_SCIM_USERS_FILE", tmp_path / "scim_users.json")
    monkeypatch.setattr(scim_mod, "_store", None)
    from chat_app.scim import SCIMUserStore
    return SCIMUserStore()


class TestSCIMUserCreation:

    def test_create_user(self, store):
        user = store.create({
            "userName": "john@example.com",
            "displayName": "John Doe",
            "emails": [{"value": "john@example.com", "primary": True}],
        })
        assert user.user_name == "john@example.com"
        assert user.display_name == "John Doe"
        assert user.active is True
        assert user.id  # Should have an ID

    def test_duplicate_username_raises(self, store):
        store.create({"userName": "john@example.com"})
        with pytest.raises(ValueError, match="already exists"):
            store.create({"userName": "john@example.com"})

    def test_create_with_external_id(self, store):
        user = store.create({
            "userName": "jane@example.com",
            "externalId": "ext_12345",
        })
        assert user.external_id == "ext_12345"


class TestSCIMUserRetrieval:

    def test_get_by_id(self, store):
        created = store.create({"userName": "test@example.com"})
        retrieved = store.get(created.id)
        assert retrieved is not None
        assert retrieved.user_name == "test@example.com"

    def test_get_by_username(self, store):
        store.create({"userName": "findme@example.com"})
        user = store.get_by_username("findme@example.com")
        assert user is not None

    def test_get_nonexistent(self, store):
        assert store.get("nonexistent") is None
        assert store.get_by_username("nobody") is None


class TestSCIMUserUpdate:

    def test_update_display_name(self, store):
        user = store.create({"userName": "test@example.com", "displayName": "Old Name"})
        updated = store.update(user.id, {"displayName": "New Name"})
        assert updated.display_name == "New Name"

    def test_deactivate_user(self, store):
        user = store.create({"userName": "test@example.com"})
        updated = store.update(user.id, {"active": False})
        assert updated.active is False

    def test_update_nonexistent(self, store):
        assert store.update("nonexistent", {"active": False}) is None


class TestSCIMUserDeletion:

    def test_soft_delete(self, store):
        user = store.create({"userName": "delete_me@example.com"})
        assert store.delete(user.id) is True
        # User still exists but is inactive
        retrieved = store.get(user.id)
        assert retrieved is not None
        assert retrieved.active is False

    def test_delete_nonexistent(self, store):
        assert store.delete("nonexistent") is False


class TestSCIMUserListing:

    def test_list_all(self, store):
        store.create({"userName": "user1@example.com"})
        store.create({"userName": "user2@example.com"})
        store.create({"userName": "user3@example.com"})
        users, total = store.list_users()
        assert total == 3
        assert len(users) == 3

    def test_list_with_filter(self, store):
        store.create({"userName": "john@example.com"})
        store.create({"userName": "jane@example.com"})
        users, total = store.list_users(filter_str='userName eq "john@example.com"')
        assert total == 1
        assert users[0].user_name == "john@example.com"

    def test_list_active_filter(self, store):
        u1 = store.create({"userName": "active@example.com"})
        u2 = store.create({"userName": "inactive@example.com"})
        store.update(u2.id, {"active": False})
        users, total = store.list_users(filter_str='active eq true')
        assert total == 1

    def test_pagination(self, store):
        for i in range(10):
            store.create({"userName": f"user{i}@example.com"})
        page1, total = store.list_users(start_index=1, count=3)
        page2, _ = store.list_users(start_index=4, count=3)
        assert total == 10
        assert len(page1) == 3
        assert len(page2) == 3


class TestSCIMSerialization:

    def test_to_scim_format(self, store):
        user = store.create({
            "userName": "test@example.com",
            "displayName": "Test User",
            "emails": [{"value": "test@example.com", "primary": True}],
        })
        scim = user.to_scim()
        assert scim["schemas"] == ["urn:ietf:params:scim:schemas:core:2.0:User"]
        assert scim["userName"] == "test@example.com"
        assert "meta" in scim
        assert scim["meta"]["resourceType"] == "User"

    def test_primary_email(self, store):
        user = store.create({
            "userName": "test@example.com",
            "emails": [
                {"value": "secondary@example.com", "primary": False},
                {"value": "primary@example.com", "primary": True},
            ],
        })
        assert user.primary_email == "primary@example.com"


class TestSCIMPersistence:

    def test_save_and_reload(self, store, tmp_path, monkeypatch):
        import chat_app.scim as scim_mod
        store.create({"userName": "persist@example.com", "displayName": "Persist"})

        # Reload
        from chat_app.scim import SCIMUserStore
        store2 = SCIMUserStore()
        user = store2.get_by_username("persist@example.com")
        assert user is not None
        assert user.display_name == "Persist"


class TestSCIMStats:

    def test_stats(self, store):
        store.create({"userName": "active@example.com"})
        u2 = store.create({"userName": "inactive@example.com"})
        store.delete(u2.id)
        stats = store.get_stats()
        assert stats["total_users"] == 2
        assert stats["active_users"] == 1
        assert stats["inactive_users"] == 1
