from rest_framework import serializers
from Smartscope.core.models.screening_session import ScreeningSession


class SessionSerializer(serializers.ModelSerializer):
    group = serializers.CharField(source="group.name", read_only=True)
    group_id = serializers.CharField(source="group.id", read_only=True)
    microscope = serializers.CharField(source="microscope_id.name", read_only=True)
    user = serializers.CharField(source="user.username", read_only=True)
    last_update = serializers.DateTimeField(read_only=True)
    grid_id = serializers.CharField(read_only=True)
    grid_count = serializers.IntegerField(read_only=True)
    grid_good = serializers.IntegerField(read_only=True)
    grid_bad = serializers.IntegerField(read_only=True)
    session_type = serializers.CharField()
    session_label = serializers.SerializerMethodField()

    def get_session_label(self, obj):
        return f"{obj.date}_{obj.session}"

    class Meta:
        model = ScreeningSession
        fields = [
            "session_label",
            "session_id",
            "group",
            "group_id",
            "microscope",
            "user",
            "creation_time",
            "last_update",
            "session_type",
            "grid_id",
            "grid_count",
            "grid_good",
            "grid_bad"
        ]